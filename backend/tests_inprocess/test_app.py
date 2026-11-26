"""End-to-end checks of the API against an in-memory database. See conftest.py."""
import uuid
from datetime import datetime, timedelta, timezone

import core
import workers


def H(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


FUTURE =(datetime.now(timezone.utc) + timedelta(days=7)).date().isoformat()
FAR = (datetime.now(timezone.utc) + timedelta(days=10)).date().isoformat()
PAST = (datetime.now(timezone.utc) - timedelta(days=10)).date().isoformat()


def book(client, parent, tutor_id, date=FUTURE, time="09:00", duration=60):
    return client.post("/api/bookings", headers=parent["h"], json={
        "tutor_id": tutor_id, "date": date, "time": time, "duration_minutes": duration, "language": "Spanish"})


def book_and_pay(client, parent, tutor_id, **kw):
    r = book(client, parent, tutor_id, **kw)
    assert r.status_code == 200, r.text
    r = client.post(f"/api/bookings/{r.json()['id']}/confirm-mock", headers=parent["h"])
    assert r.status_code == 200, r.text
    return r.json()


def insert_booking(db_call, parent, tutor_profile, start: datetime, duration=60, **extra):
    b = {
        "id": str(uuid.uuid4()), "parent_id": parent["user"]["id"], "parent_name": parent["user"]["name"],
        "tutor_id": tutor_profile["id"], "tutor_name": tutor_profile["name"],
        "date": start.date().isoformat(), "time": f"{start.hour:02d}:{start.minute:02d}", "timezone": "UTC",
        "duration_minutes": duration, "language": "Spanish", "amount_cents": 3535, "platform_fee_cents": 35,
        "currency": "usd", "payment_status": "paid", "stripe_payment_intent_id": f"pi_mock_{uuid.uuid4()}",
        "client_secret": None, "notes": "", "is_au_pair": False, "lessons_count": 1, "remote": True,
        "housing_offered": "", "tutor_response": "accepted", "created_at": core.now_iso(), **extra,
    }
    db_call(core.db.bookings.insert_one, dict(b))
    return b


# ---- Bookings: identity, double-booking, validation ----
def test_tutor_sees_and_opens_their_bookings(client, make_user, sofia):
    parent = make_user()
    bk = book_and_pay(client, parent, sofia["profile"]["id"], time="9:00")
    assert bk["time"] == "09:00"
    assert bk["timezone"] == "Europe/Madrid"
    assert any(b["id"] == bk["id"] for b in client.get("/api/bookings/me", headers=sofia["h"]).json())
    assert client.get(f"/api/bookings/{bk['id']}", headers=sofia["h"]).status_code == 200
    notes = client.get("/api/notifications", headers=sofia["h"]).json()
    assert any(n["title"] == "New booking request" for n in notes)


def test_overlapping_sessions_blocked(client, make_user, sofia):
    parent = make_user()
    book_and_pay(client, parent, sofia["profile"]["id"], date=FAR, time="09:00", duration=120)
    assert book(client, parent, sofia["profile"]["id"], date=FAR, time="09:00").status_code == 409
    assert book(client, parent, sofia["profile"]["id"], date=FAR, time="10:00").status_code == 409  # inside the 2h
    assert book(client, parent, sofia["profile"]["id"], date=FAR, time="08:00", duration=90).status_code == 409
    assert book(client, parent, sofia["profile"]["id"], date=FAR, time="11:00").status_code == 200  # right after
    slots = client.get(f"/api/tutors/{sofia['profile']['id']}/booked-slots").json()
    assert {"date": FAR, "time": "10:00"} in slots


def test_booking_validation(client, make_user, sofia):
    parent = make_user()
    assert book(client, parent, sofia["profile"]["id"], date=PAST).status_code == 400
    assert book(client, parent, sofia["profile"]["id"], date="next tuesday").status_code == 422
    assert book(client, parent, sofia["profile"]["id"], time="25:00").status_code == 422
    r = client.get("/api/tutors", params={"language": "(a+)+$["})
    assert r.status_code == 200 and r.json() == []
    assert client.patch("/api/tutors/me/profile", headers=sofia["h"], json={"hourly_rate_cents": -500}).status_code == 422


# ---- Reviews ----
def test_reviews_need_a_finished_paid_session(client, make_user, sofia, db_call):
    parent = make_user()
    upcoming = book_and_pay(client, parent, sofia["profile"]["id"], date=FUTURE, time="15:00")
    review = {"tutor_id": sofia["profile"]["id"], "rating": 5}
    assert client.post("/api/reviews", headers=parent["h"], json={**review, "booking_id": upcoming["id"]}).status_code == 400
    assert client.post("/api/reviews", headers=parent["h"], json={**review, "booking_id": "nope"}).status_code == 403
    past = insert_booking(db_call, parent, sofia["profile"], datetime.now(timezone.utc) - timedelta(days=2))
    r = client.post("/api/reviews", headers=parent["h"], json={**review, "booking_id": past["id"], "comment": " Lovely "})
    assert r.status_code == 200 and r.json()["comment"] == "Lovely"
    assert client.post("/api/reviews", headers=parent["h"], json={**review, "booking_id": past["id"]}).status_code == 409


# ---- Invitations ----
def test_invitation_lifecycle(client, make_user, sofia):
    parent = make_user()
    # The family has to have contacted the tutor first for the profile, but invitations only need a parent.
    def invite(t):
        return client.post("/api/messages/invitation", headers=sofia["h"], json={
            "to_user_id": parent["user"]["id"], "price_cents": 4000, "date": FUTURE, "time": t,
            "duration_minutes": 60, "language": "Spanish"})
    r = invite("17:00")
    assert r.status_code == 200, r.text
    mid = r.json()["id"]
    assert client.post(f"/api/messages/invitation/{mid}/decline", headers=parent["h"]).status_code == 200
    assert client.post(f"/api/messages/invitation/{mid}/decline", headers=parent["h"]).status_code == 400
    assert client.post(f"/api/messages/invitation/{mid}/accept", headers=parent["h"]).status_code == 400
    mid2 = invite("18:00").json()["id"]
    r = client.post(f"/api/messages/invitation/{mid2}/accept", headers=parent["h"])
    assert r.status_code == 200 and r.json()["tutor_response"] == "accepted"
    assert client.post(f"/api/messages/invitation/{mid2}/accept", headers=parent["h"]).status_code in (400, 409)


# ---- Uploads ----
def test_uploads_are_typed_by_extension_and_capped(client, make_user):
    parent = make_user()
    r = client.post("/api/uploads", headers=parent["h"], files={"file": ("x.html", b"<script>alert(1)</script>", "text/html")})
    assert r.status_code == 200 and r.json()["content_type"] == "image/jpeg"
    big = b"0" * (core.MAX_UPLOAD_BYTES + 1)
    assert client.post("/api/uploads", headers=parent["h"], files={"file": ("big.jpg", big, "image/jpeg")}).status_code == 413


# ---- Email verification + password reset ----
def test_email_verification(client, make_user, codes):
    u = make_user()
    assert u["user"]["email_verified"] is False
    code = codes[(u["email"], "verify")]
    assert client.post("/api/auth/verify-email", headers=u["h"], json={"code": "000000" if code != "000000" else "111111"}).status_code == 400
    r = client.post("/api/auth/verify-email", headers=u["h"], json={"code": code})
    assert r.status_code == 200 and r.json()["email_verified"] is True


def test_password_reset(client, make_user, codes):
    u = make_user()
    r = client.post("/api/auth/forgot-password", json={"email": u["email"]})
    assert r.status_code == 200
    same = client.post("/api/auth/forgot-password", json={"email": "nobody@example.com"})
    assert same.json() == r.json()  # doesn't reveal who has an account
    code = codes[(u["email"], "reset")]
    r = client.post("/api/auth/reset-password", json={"email": u["email"], "code": code, "new_password": "brand-new-pass"})
    assert r.status_code == 200, r.text
    assert client.get("/api/auth/me", headers=u["h"]).status_code == 401  # old sessions are signed out
    assert client.post("/api/auth/login", json={"email": u["email"], "password": "brand-new-pass"}).status_code == 200
    # A code works once.
    again = client.post("/api/auth/reset-password", json={"email": u["email"], "code": code, "new_password": "another-pass1"})
    assert again.status_code == 400


def test_reset_code_locks_after_too_many_guesses(client, make_user, codes):
    u = make_user()
    client.post("/api/auth/forgot-password", json={"email": u["email"]})
    real = codes[(u["email"], "reset")]
    wrong = "123456" if real != "123456" else "654321"
    for _ in range(5):
        client.post("/api/auth/reset-password", json={"email": u["email"], "code": wrong, "new_password": "whatever12"})
    r = client.post("/api/auth/reset-password", json={"email": u["email"], "code": real, "new_password": "whatever12"})
    assert r.status_code == 400


# ---- Time zones ----
def test_timezones(client, make_user):
    tutor = make_user("tutor", tz="America/New_York")
    assert tutor["user"]["timezone"] == "America/New_York"
    prof = client.get("/api/tutors/me/profile", headers=tutor["h"]).json()
    assert prof["timezone"] == "America/New_York"
    assert client.patch("/api/tutors/me/profile", headers=tutor["h"], json={"timezone": "Mars/Olympus"}).status_code == 422
    start = core.local_start("2030-01-15", "09:00", "America/New_York")
    assert start.astimezone(timezone.utc).hour == 14  # 9am New York in January = 14:00 UTC


# ---- Cancel / reschedule / tutor response ----
def test_tutor_accepts_request(client, make_user, sofia):
    parent = make_user()
    bk = book_and_pay(client, parent, sofia["profile"]["id"], date=FAR, time="13:00")
    assert bk["tutor_response"] == "pending" and bk["respond_by"]
    assert client.post(f"/api/bookings/{bk['id']}/respond", headers=parent["h"], json={"accept": True}).status_code == 403
    r = client.post(f"/api/bookings/{bk['id']}/respond", headers=sofia["h"], json={"accept": True, "note": "See you!"})
    assert r.status_code == 200 and r.json()["tutor_response"] == "accepted"
    assert client.post(f"/api/bookings/{bk['id']}/respond", headers=sofia["h"], json={"accept": True}).status_code == 400


def test_tutor_declines_and_parent_is_refunded(client, make_user, sofia):
    parent = make_user()
    bk = book_and_pay(client, parent, sofia["profile"]["id"], date=FAR, time="14:00")
    r = client.post(f"/api/bookings/{bk['id']}/respond", headers=sofia["h"], json={"accept": False, "note": "Away that week"})
    b = r.json()
    assert b["payment_status"] == "canceled" and b["refund_status"] == "refunded" and b["refund_cents"] == bk["amount_cents"]
    assert book(client, parent, sofia["profile"]["id"], date=FAR, time="14:00").status_code == 200  # slot is free again


def test_parent_cancel_policy(client, make_user, sofia, db_call):
    parent = make_user()
    early = book_and_pay(client, parent, sofia["profile"]["id"], date=FAR, time="16:00")
    client.post(f"/api/bookings/{early['id']}/respond", headers=sofia["h"], json={"accept": True})
    preview = client.get(f"/api/bookings/{early['id']}/cancel-preview", headers=parent["h"]).json()
    assert preview["refund_cents"] == early["amount_cents"]
    r = client.post(f"/api/bookings/{early['id']}/cancel", headers=parent["h"], json={"reason": "Plans changed"})
    assert r.json()["refund_status"] == "refunded"
    assert client.post(f"/api/bookings/{early['id']}/cancel", headers=parent["h"]).status_code == 400
    # Accepted session starting in 3 hours → inside the 24h window → no refund.
    late = insert_booking(db_call, parent, sofia["profile"], datetime.now(timezone.utc) + timedelta(hours=3))
    r = client.post(f"/api/bookings/{late['id']}/cancel", headers=parent["h"])
    assert r.json()["refund_status"] == "not_refunded" and r.json()["refund_cents"] == 0


def test_reschedule(client, make_user, sofia, db_call):
    day = (datetime.now(timezone.utc) + timedelta(days=12)).date().isoformat()
    parent = make_user()
    bk = book_and_pay(client, parent, sofia["profile"]["id"], date=day, time="19:00")
    book_and_pay(client, parent, sofia["profile"]["id"], date=day, time="11:00")
    assert client.post(f"/api/bookings/{bk['id']}/reschedule", headers=parent["h"], json={"date": day, "time": "11:00"}).status_code == 409
    r = client.post(f"/api/bookings/{bk['id']}/reschedule", headers=parent["h"], json={"date": day, "time": "20:00"})
    assert r.status_code == 200 and r.json()["time"] == "20:00" and r.json()["reschedule_count"] == 1
    # The old slot is free again; too-close sessions can't be moved.
    assert book(client, parent, sofia["profile"]["id"], date=day, time="19:00").status_code == 200
    soon = insert_booking(db_call, parent, sofia["profile"], datetime.now(timezone.utc) + timedelta(hours=5))
    assert client.post(f"/api/bookings/{soon['id']}/reschedule", headers=parent["h"], json={"date": day, "time": "21:00"}).status_code == 400


def test_worker_expires_unpaid_and_unanswered(client, make_user, sofia, db_call):
    parent = make_user()
    unpaid = book(client, parent, sofia["profile"]["id"], date=FAR, time="08:00").json()
    old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    db_call(core.db.bookings.update_one, {"id": unpaid["id"]}, {"$set": {"created_at": old}})
    request = book_and_pay(client, parent, sofia["profile"]["id"], date=FAR, time="12:00")
    db_call(core.db.bookings.update_one, {"id": request["id"]}, {"$set": {"respond_by": old}})
    db_call(workers.run_once)
    assert client.get(f"/api/bookings/{unpaid['id']}", headers=parent["h"]).json()["payment_status"] == "canceled"
    b = client.get(f"/api/bookings/{request['id']}", headers=parent["h"]).json()
    assert b["payment_status"] == "canceled" and b["refund_status"] == "refunded" and b["canceled_by"] == "system"


def test_reminders_respect_timezone(client, make_user, sofia, db_call):
    parent = make_user()
    soon = insert_booking(db_call, parent, sofia["profile"], datetime.now(timezone.utc) + timedelta(minutes=60))
    db_call(workers.run_once)
    kinds = {n["kind"] for n in client.get("/api/notifications", headers=parent["h"]).json()}
    assert f"reminder:{soon['id']}" in kinds


# ---- Verification ----
def test_tutor_verification_flow(client, make_user, sofia, db_call):
    tutor = make_user("tutor")
    up = lambda name: client.post("/api/uploads", headers=tutor["h"], files={"file": (name, b"%PDF-1.4", "application/pdf")}).json()["path"]  # noqa: E731
    id_doc, check = up("id.pdf"), up("check.pdf")
    assert client.post("/api/tutors/me/verification", headers=tutor["h"], json={"id_document_url": id_doc, "background_check_url": check, "consent": False}).status_code == 422
    r = client.post("/api/tutors/me/verification", headers=tutor["h"], json={"id_document_url": id_doc, "background_check_url": check, "consent": True})
    assert r.status_code == 200 and r.json()["status"] == "pending"
    # Identity documents are private: another signed-in user can't open them.
    stranger = make_user()
    assert client.get(f"/api/files/{id_doc}", headers=stranger["h"]).status_code == 403
    # Admin approves → badge appears and the verified filter finds them.
    admin_tok = core.make_token("admin-test", "admin", admin=True)
    db_call(core.db.users.insert_one, {"id": "admin-test", "email": "admin@example.com", "name": "Admin", "role": "admin", "is_admin": True, "password_hash": "x"})
    pending = client.get("/api/admin/verifications", headers=H(admin_tok)).json()
    me = next(p for p in pending if p["user_id"] == tutor["user"]["id"])
    assert client.post(f"/api/admin/verifications/{me['id']}/approve", headers=H(admin_tok), json={}).status_code == 200
    assert client.get(f"/api/tutors/{me['id']}").json()["verified"] is True
    assert me["id"] in [t["id"] for t in client.get("/api/tutors", params={"verified_only": "true"}).json()]


# ---- Push tokens ----
def test_push_token_registration(client, make_user, db_call):
    u = make_user()
    assert client.post("/api/push-tokens", headers=u["h"], json={"token": "not-a-token-at-all"}).status_code == 422
    tok = "ExponentPushToken[abc123xyz]"
    assert client.post("/api/push-tokens", headers=u["h"], json={"token": tok, "platform": "ios"}).status_code == 200
    assert db_call(core.db.push_tokens.count_documents, {"user_id": u["user"]["id"]}) == 1
    assert client.delete("/api/push-tokens", headers=u["h"], params={"token": tok}).status_code == 200
    assert db_call(core.db.push_tokens.count_documents, {"user_id": u["user"]["id"]}) == 0


# ---- Account deletion keeps anonymised records ----
def test_parent_deletion_keeps_anonymised_history(client, make_user, sofia, db_call):
    parent = make_user()
    past = insert_booking(db_call, parent, sofia["profile"], datetime.now(timezone.utc) - timedelta(days=3))
    upcoming = book_and_pay(client, parent, sofia["profile"]["id"], date=FAR, time="07:00")
    assert client.delete("/api/auth/me", headers=parent["h"]).status_code == 200
    kept = db_call(core.db.bookings.find_one, {"id": past["id"]}, {"_id": 0})
    assert kept and kept["parent_name"] == "Deleted user"
    cancelled = db_call(core.db.bookings.find_one, {"id": upcoming["id"]}, {"_id": 0})
    assert cancelled["payment_status"] == "canceled"


# ---- SEO ----
def test_share_pages_and_sitemap(client, sofia):
    r = client.get(f"/api/share/tutor/{sofia['profile']['id']}")
    assert r.status_code == 200 and "og:title" in r.text and "Sof" in r.text
    assert client.get("/api/share/tutor/nope").status_code == 404
    posts = client.get("/api/posts").json()
    assert client.get(f"/api/share/blog/{posts[0]['id']}").status_code == 200
    sm = client.get("/api/seo/sitemap.xml")
    assert sm.status_code == 200 and "<urlset" in sm.text and "/api/share/tutor/" in sm.text


# ---- File storage (local folder backend) ----
def test_upload_round_trip_and_private_files(client, make_user):
    u = make_user()
    up = client.post("/api/uploads", headers=u["h"], files={"file": ("a.png", b"\x89PNG-bytes", "image/png")}).json()
    assert client.get(up["url"]).status_code == 401  # not used anywhere yet -> owner only
    r = client.get(up["url"], headers=u["h"])
    assert r.status_code == 200 and r.content == b"\x89PNG-bytes" and r.headers["content-type"] == "image/png"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert client.get("/api/files/babybabel/uploads/nobody/missing.png").status_code == 404


def test_storage_rejects_path_tricks():
    import pytest
    import storage
    for bad in ("../secret.txt", "/etc/passwd", "a/../../b", "a\\..\\b", ""):
        with pytest.raises(storage.StorageError):
            storage.put_object(bad, b"x", "text/plain")
    storage.put_object("babybabel/uploads/t/ok.txt", b"hello", "text/plain; charset=utf-8")
    assert storage.get_object("babybabel/uploads/t/ok.txt") == (b"hello", "text/plain; charset=utf-8")
    assert storage.delete_object("babybabel/uploads/t/ok.txt") is True
    with pytest.raises(storage.NotFound):
        storage.get_object("babybabel/uploads/t/ok.txt")


def test_mock_confirm_can_be_switched_off(client, make_user, sofia, monkeypatch):
    parent = make_user()
    r = book(client, parent, sofia["profile"]["id"], date=(datetime.now(timezone.utc) + timedelta(days=13)).date().isoformat(), time="10:00")
    monkeypatch.setenv("ENABLE_MOCK_CONFIRM", "false")
    assert client.post(f"/api/bookings/{r.json()['id']}/confirm-mock", headers=parent["h"]).status_code == 410


# ---- Local dev database (MONGO_URL=memory://…) ----
def test_dev_database_survives_a_restart(tmp_path):
    import asyncio

    import devdb
    from mongomock_motor import AsyncMongoMockClient

    snap = devdb.snapshot_path(f"memory://{tmp_path / 'dev-db.json'}")
    assert devdb.snapshot_path("memory://") is None

    async def scenario():
        first = AsyncMongoMockClient()["dev"]
        await first.users.insert_one({"id": "u1", "email": "a@example.com", "when": datetime.now(timezone.utc)})
        await first.bookings.insert_many([{"id": "b1"}, {"id": "b2"}])
        await devdb.save(first, snap)
        second = AsyncMongoMockClient()["dev"]  # a fresh process
        loaded = await devdb.load(second, snap)
        return loaded, await second.users.find_one({"id": "u1"}, {"_id": 0}), await second.bookings.count_documents({})

    loaded, user, n = asyncio.run(scenario())
    assert loaded == 3 and n == 2 and user["email"] == "a@example.com"
    assert isinstance(user["when"], datetime)


# ---- Verification is required before a tutor can be booked ----
def test_unverified_tutor_is_hidden_and_cannot_be_booked(client, make_user):
    tutor = make_user("tutor")
    prof = client.get("/api/tutors/me/profile", headers=tutor["h"]).json()
    parent = make_user()
    assert prof["id"] not in [t["id"] for t in client.get("/api/tutors").json()]
    assert prof["id"] not in [p["id"] for p in client.get("/api/tutors/map").json()]
    assert client.get(f"/api/tutors/{prof['id']}", headers=parent["h"]).status_code == 404
    assert client.get(f"/api/tutors/{prof['id']}", headers=tutor["h"]).status_code == 200  # owner can preview
    assert client.get(f"/api/share/tutor/{prof['id']}").status_code == 404
    r = book(client, parent, prof["id"])
    assert r.status_code == 400 and "verification" in r.json()["detail"]
    offer = client.post("/api/messages/invitation", headers=tutor["h"], json={
        "to_user_id": parent["user"]["id"], "price_cents": 4000, "date": FUTURE, "time": "10:00",
        "duration_minutes": 60, "language": "Spanish"})
    assert offer.status_code == 403 and "verification" in offer.json()["detail"]


def test_sample_tutors_only_on_request(db_call):
    import os

    import seed
    os.environ["SEED_SAMPLE_TUTORS"] = "false"
    try:
        db_call(seed.seed_data)
        assert db_call(core.db.users.count_documents, {"email": {"$regex": r"@babybabel\.dev$"}}) == 0
    finally:
        os.environ["SEED_SAMPLE_TUTORS"] = "true"
        db_call(seed.seed_data)
    assert db_call(core.db.users.count_documents, {"email": {"$regex": r"@babybabel\.dev$"}}) == 2


# ---- Keeping data minimal ----
def test_usage_events_are_anonymous(client, make_user, db_call):
    u = make_user()
    marker = f"evt-{uuid.uuid4().hex[:6]}"
    client.post("/api/events", headers=u["h"], json={"name": marker, "props": {
        "tutor_id": "t1", "conversation_id": "u2", "booking_id": "b1", "email": "x@y.z", "user_name": "Pat",
        "language": "Spanish", "rating": 5, "has_comment": True, "long": "x" * 200}})
    ev = db_call(core.db.events.find_one, {"name": marker}, {"_id": 0})
    assert "user_id" not in ev and "user_name" not in ev
    assert ev["props"] == {"language": "Spanish", "rating": 5, "has_comment": True}


def test_old_and_unused_data_is_deleted(client, make_user, db_call):
    u = make_user()
    old = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
    db_call(core.db.notifications.insert_one, {"id": "n-old", "user_id": u["user"]["id"], "kind": "chat", "title": "t", "body": "b", "read": False, "at": old})
    db_call(core.db.events.insert_one, {"name": "old-evt", "role": "parent", "props": {}, "at": old})
    db_call(core.db.push_tokens.insert_one, {"token": "ExponentPushToken[old]", "user_id": u["user"]["id"], "updated_at": old})
    db_call(core.db.auth_codes.insert_one, {"user_id": "x", "purpose": "reset", "code_hash": "h", "attempts": 0, "expires_at": old})
    # Two uploads: one used as the avatar, one abandoned. Both "old enough".
    keep = client.post("/api/uploads", headers=u["h"], files={"file": ("a.png", b"keep", "image/png")}).json()["path"]
    drop = client.post("/api/uploads", headers=u["h"], files={"file": ("b.png", b"drop", "image/png")}).json()["path"]
    client.patch("/api/auth/me", headers=u["h"], json={"avatar_url": keep})
    db_call(core.db.uploads.update_many, {"path": {"$in": [keep, drop]}}, {"$set": {"created_at": old}})

    counts = db_call(workers.purge_short_lived_records)
    removed = db_call(workers.purge_orphan_uploads)

    assert counts["notifications"] >= 1 and counts["events"] >= 1 and counts["push_tokens"] >= 1 and counts["auth_codes"] >= 1
    assert removed >= 1
    assert db_call(core.db.uploads.find_one, {"path": keep}, {"_id": 1}) is not None
    assert db_call(core.db.uploads.find_one, {"path": drop}, {"_id": 1}) is None
    assert client.get(f"/api/files/{keep}").status_code == 200
    assert client.get(f"/api/files/{drop}").status_code == 404
