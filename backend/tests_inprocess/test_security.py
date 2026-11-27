"""Security regression tests: families' payment and personal information.

Each test is an attack attempt. They must keep passing — a failure means data can leak.
"""
import uuid
from datetime import datetime, timedelta, timezone

import core

FUTURE = (datetime.now(timezone.utc) + timedelta(days=9)).date().isoformat()


def H(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def parent_with_child_photo(client, make_user):
    """A family whose profile has a child with a (private) photo."""
    p = make_user()
    photo = client.post("/api/uploads", headers=p["h"], files={"file": ("kid.jpg", b"child-photo", "image/jpeg")}).json()["path"]
    r = client.patch("/api/parents/me/profile", headers=p["h"], json={
        "city": "", "children": [{"name": "Mia", "age": 4, "avatar_url": photo}]})
    assert r.status_code == 200, r.text
    return p, photo


def booked(client, parent, tutor_id, time="15:00"):
    r = client.post("/api/bookings", headers=parent["h"], json={
        "tutor_id": tutor_id, "date": FUTURE, "time": time, "duration_minutes": 60, "language": "Spanish"})
    assert r.status_code == 200, r.text
    return r.json()


# ---- Payments ----
def test_payment_secret_only_goes_to_the_paying_parent(client, make_user, sofia):
    parent = make_user()
    b = booked(client, parent, sofia["profile"]["id"], "07:00")
    assert client.get(f"/api/bookings/{b['id']}", headers=parent["h"]).json()["client_secret"]
    as_tutor = client.get(f"/api/bookings/{b['id']}", headers=sofia["h"]).json()
    assert as_tutor["client_secret"] is None and as_tutor["stripe_payment_intent_id"] is None
    listed = [x for x in client.get("/api/bookings/me", headers=sofia["h"]).json() if x["id"] == b["id"]][0]
    assert listed["client_secret"] is None


def test_strangers_cannot_see_or_change_a_booking(client, make_user, sofia):
    parent, other = make_user(), make_user()
    b = booked(client, parent, sofia["profile"]["id"], "08:00")
    for method, path, body in [
        ("get", f"/api/bookings/{b['id']}", None),
        ("post", f"/api/bookings/{b['id']}/confirm-mock", None),
        ("post", f"/api/bookings/{b['id']}/cancel", {}),
        ("post", f"/api/bookings/{b['id']}/reschedule", {"date": FUTURE, "time": "19:00"}),
        ("get", f"/api/bookings/{b['id']}/cancel-preview", None),
    ]:
        r = getattr(client, method)(path, headers=other["h"], **({"json": body} if body is not None else {}))
        assert r.status_code == 403, f"{method} {path} -> {r.status_code}"
    assert client.post(f"/api/bookings/{b['id']}/respond", headers=parent["h"], json={"accept": True}).status_code == 403


def test_amount_is_set_by_the_server(client, make_user, sofia):
    parent = make_user()
    r = client.post("/api/bookings", headers=parent["h"], json={
        "tutor_id": sofia["profile"]["id"], "date": FUTURE, "time": "09:00", "duration_minutes": 60,
        "language": "Spanish", "amount_cents": 1, "platform_fee_cents": 0})
    assert r.json()["amount_cents"] == 3500 + 35  # $35/h + 1%, whatever the client sends


# ---- Family profile and children ----
def test_family_profile_is_private(client, make_user, sofia):
    parent, photo = parent_with_child_photo(client, make_user)
    stranger_tutor = make_user("tutor")
    stranger_parent = make_user()
    pid = parent["user"]["id"]
    assert client.get(f"/api/parents/{pid}/public").status_code == 401
    assert client.get(f"/api/parents/{pid}/public", headers=stranger_tutor["h"]).status_code == 403
    assert client.get(f"/api/parents/{pid}/public", headers=stranger_parent["h"]).status_code == 403
    # A tutor the family booked sees first names and ages, but no photos or location.
    booked(client, parent, sofia["profile"]["id"], "10:00")
    seen = client.get(f"/api/parents/{pid}/public", headers=sofia["h"]).json()
    assert seen["children"][0]["name"] == "Mia" and seen["children"][0]["avatar_url"] is None
    assert seen["latitude"] is None and seen["longitude"] is None


def test_child_photos_only_reach_their_parent(client, make_user, sofia):
    parent, photo = parent_with_child_photo(client, make_user)
    assert client.get(f"/api/files/{photo}", headers=parent["h"]).content == b"child-photo"
    assert client.get(f"/api/files/{photo}").status_code == 401
    assert client.get(f"/api/files/{photo}", headers=sofia["h"]).status_code == 403


def test_cannot_claim_someone_elses_file(client, make_user):
    """Pointing your own profile at another family's private photo must not unlock it."""
    victim, photo = parent_with_child_photo(client, make_user)
    attacker = make_user()
    for patch in ({"children": [{"name": "X", "age": 3, "avatar_url": photo}]}, {"avatar_url": photo}):
        r = client.patch("/api/parents/me/profile", headers=attacker["h"], json=patch)
        assert r.status_code == 422, f"accepted {patch}: {r.status_code}"
    assert client.patch("/api/auth/me", headers=attacker["h"], json={"avatar_url": photo}).status_code == 422
    assert client.get(f"/api/files/{photo}", headers=attacker["h"]).status_code == 403


def test_unused_uploads_are_private_to_their_owner(client, make_user):
    owner, other = make_user(), make_user()
    path = client.post("/api/uploads", headers=owner["h"], files={"file": ("doc.pdf", b"%PDF-private", "application/pdf")}).json()["path"]
    assert client.get(f"/api/files/{path}", headers=owner["h"]).status_code == 200
    assert client.get(f"/api/files/{path}").status_code == 401
    assert client.get(f"/api/files/{path}", headers=other["h"]).status_code == 403


def test_reviews_show_first_name_and_initial_only(client, make_user, sofia, db_call):
    parent = make_user()
    client.patch("/api/auth/me", headers=parent["h"], json={"name": "Patricia Longsurname"})
    b = {
        "id": str(uuid.uuid4()), "parent_id": parent["user"]["id"], "parent_name": "Patricia Longsurname",
        "tutor_id": sofia["profile"]["id"], "tutor_name": "Sofía García", "date": "2026-01-10", "time": "10:00",
        "timezone": "UTC", "duration_minutes": 60, "language": "Spanish", "amount_cents": 3535,
        "platform_fee_cents": 35, "currency": "usd", "payment_status": "paid", "tutor_response": "accepted",
        "created_at": core.now_iso(),
    }
    db_call(core.db.bookings.insert_one, dict(b))
    parent_tok = core.make_token(parent["user"]["id"], "parent")
    r = client.post("/api/reviews", headers=H(parent_tok), json={"tutor_id": sofia["profile"]["id"], "booking_id": b["id"], "rating": 5})
    assert r.status_code == 200, r.text
    public = client.get(f"/api/reviews/tutor/{sofia['profile']['id']}").json()
    mine = [x for x in public if x["booking_id"] == b["id"]][0]
    assert mine["parent_name"] == "Patricia L."
    assert "parent_id" not in mine or mine["parent_id"] in (None, "")


# ---- Accounts ----
def test_private_endpoints_need_sign_in_and_admin(client, make_user):
    parent = make_user()
    for path in ("/api/parents/me/profile", "/api/bookings/me", "/api/messages/threads", "/api/notifications"):
        assert client.get(path).status_code == 401, path
    for path in ("/api/admin/users", "/api/admin/stats", "/api/admin/blocks", "/api/admin/w9", "/api/admin/verifications"):
        assert client.get(path, headers=parent["h"]).status_code == 403, path


def test_password_reset_is_limited_per_email_not_just_per_ip(client, make_user):
    victim = make_user()
    codes = []
    for i in range(8):
        r = client.post("/api/auth/forgot-password", json={"email": victim["email"]}, headers={"X-Forwarded-For": f"198.51.100.{i}"})
        codes.append(r.status_code)
    assert 429 in codes, f"no limit across IPs: {codes}"


def test_message_text_stays_off_lock_screens():
    assert core.push_text("chat", "Mia has a fever today") == "Open Babybabel to read it."
    assert core.push_text("booking", "Booking confirmed") == "Booking confirmed"


def test_signed_links_for_private_images(client, make_user, sofia):
    parent, photo = parent_with_child_photo(client, make_user)
    assert client.get("/api/files-link", params={"path": photo}, headers=sofia["h"]).status_code == 403
    link = client.get("/api/files-link", params={"path": photo}, headers=parent["h"]).json()["url"]
    assert "sig=" in link
    assert client.get(link).content == b"child-photo"  # works without the sign-in header…
    tampered = link.replace(photo, photo.replace(".jpg", "x.jpg"))
    assert client.get(tampered).status_code in (401, 404)
    # …only for that file, and not after it expires.
    path, query = link.split("?", 1)
    expired = f"{path}?exp=1000&{query.split('&', 1)[1]}"
    assert client.get(expired).status_code == 401


# ---- Website sessions: HttpOnly cookie + CSRF header; sign out everywhere ----
def _web_client():
    import server
    from fastapi.testclient import TestClient
    # Own cookie jar; https because the session cookie is Secure (as on the live site).
    return TestClient(server.app, base_url="https://testserver")


WEB = {"X-Session-Mode": "cookie", "X-Babybabel-CSRF": "1"}


def test_website_session_uses_an_httponly_cookie(make_user):
    web = _web_client()
    email = f"web-{uuid.uuid4().hex[:8]}@example.com"
    r = web.post("/api/auth/signup", headers=WEB, json={"email": email, "password": "longenough1", "name": "Web Parent", "role": "parent", "accept_terms": True})
    assert r.status_code == 201
    assert r.json()["access_token"] == ""  # nothing a script could read
    cookie = r.headers["set-cookie"].lower()
    assert "bb_session=" in cookie and "httponly" in cookie and "samesite=strict" in cookie and "path=/api" in cookie
    assert web.get("/api/auth/me").status_code == 200
    # Changes without the custom header (what a forged cross-site form would look like) are refused…
    assert web.patch("/api/auth/me", json={"name": "Hacked"}).status_code == 403
    # …and allowed with it.
    assert web.patch("/api/auth/me", headers=WEB, json={"name": "Web Parent 2"}).json()["name"] == "Web Parent 2"
    assert web.post("/api/auth/logout", headers=WEB).status_code == 200
    assert web.get("/api/auth/me").status_code == 401


def test_phone_apps_still_get_a_token(client, make_user):
    u = make_user()
    r = client.post("/api/auth/login", json={"email": u["email"], "password": "longenough1"})
    assert r.json()["access_token"] and "set-cookie" not in r.headers


def test_sign_out_everywhere(client, make_user):
    u = make_user()
    web = _web_client()
    web.post("/api/auth/login", headers=WEB, json={"email": u["email"], "password": "longenough1"})
    phone = client.post("/api/auth/login", json={"email": u["email"], "password": "longenough1"}).json()["access_token"]
    assert client.post("/api/auth/logout-all", headers=H(phone)).status_code == 200
    assert client.get("/api/auth/me", headers=H(phone)).status_code == 401
    assert client.get("/api/auth/me", headers=u["h"]).status_code == 401
    assert web.get("/api/auth/me").status_code == 401  # the browser session is gone too
    # Signing in again works.
    assert client.post("/api/auth/login", json={"email": u["email"], "password": "longenough1"}).status_code == 200


def test_share_page_script_matches_the_csp_hash():
    """The site's CSP allows exactly one inline script (share-page redirect) by hash. If the script
    changes, the hash in deploy/Caddyfile must change too, or people won't be redirected."""
    import base64
    import hashlib
    import re
    from pathlib import Path

    from routes.seo import REDIRECT_JS
    digest = "sha256-" + base64.b64encode(hashlib.sha256(REDIRECT_JS.encode()).digest()).decode()
    caddyfile = (Path(__file__).resolve().parents[2] / "deploy" / "Caddyfile").read_text(encoding="utf-8")
    assert f"'{digest}'" in caddyfile, f"update the script hash in deploy/Caddyfile to {digest}"
    assert re.search(r"script-src 'self' 'sha256-[^']+';", caddyfile), "script-src must stay strict"


def test_share_page_has_one_fixed_script(client, sofia):
    html = client.get(f"/api/share/tutor/{sofia['profile']['id']}").text
    from routes.seo import REDIRECT_JS
    assert html.count("<script>") == 1 and f"<script>{REDIRECT_JS}</script>" in html
    assert 'rel="canonical"' in html
