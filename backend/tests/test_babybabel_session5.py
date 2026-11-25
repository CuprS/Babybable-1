"""
Session-5 backend feature tests for Babybabel:

1) Distance filter on GET /api/tutors — max_miles / include_remote / distance_miles
   response field / nearest-first sort.
2) Invitation-accept response — invitation.booking_id populated on the parent-visible
   messages thread after accept.
3) Reviews — POST /api/reviews inserts + updates tutors.rating & reviews_count;
   GET /api/reviews/tutor/{id} returns review with booking_id.
4) _generate_dynamic_notifications — review:<booking_id> notification is created 30+ min
   after a paid booking ended, and is SKIPPED when a review already exists for that
   booking.

The suite is idempotent: it cleans stale docs before/after via pymongo and does not
mutate seeded tutor availability. Past-in-time bookings are injected directly via
pymongo (server endpoints reject past dates via slot logic).
"""
import os
import time
import uuid
import pytest
import requests
import pymongo
from datetime import datetime, timedelta, timezone
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

BASE = os.environ.get(
    "EXPO_PUBLIC_BACKEND_URL", "http://localhost:8001"
).rstrip("/")
_mongo = pymongo.MongoClient(os.environ["MONGO_URL"])
_db = _mongo[os.environ["DB_NAME"]]

SOFIA_EMAIL = "sofia@babybabel.dev"
SOFIA_PW = "password123"
PARENT_EMAIL = "parent@test.dev"
PARENT_PW = "password123"


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _login(email, password):
    r = requests.post(
        f"{BASE}/api/auth/login",
        json={"email": email, "password": password},
        timeout=15,
    )
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    return r.json()


@pytest.fixture(scope="module")
def parent_ctx():
    data = _login(PARENT_EMAIL, PARENT_PW)
    return {"token": data["access_token"], "user": data["user"]}


@pytest.fixture(scope="module")
def sofia_ctx():
    data = _login(SOFIA_EMAIL, SOFIA_PW)
    return {"token": data["access_token"], "user": data["user"]}


@pytest.fixture(scope="module")
def tutor_ids(sofia_ctx):
    # Look up tutor docs to map user_id -> tutor.id
    sofia = _db.tutors.find_one({"user_id": sofia_ctx["user"]["id"]}, {"_id": 0})
    assert sofia, "Sofia tutor doc missing"
    marie = _db.tutors.find_one({"name": "Marie Dubois"}, {"_id": 0})
    assert marie, "Marie tutor doc missing"
    return {"sofia": sofia["id"], "marie": marie["id"], "sofia_doc": sofia, "marie_doc": marie}


@pytest.fixture(scope="module", autouse=True)
def _cleanup_parent_state(parent_ctx):
    """Ensure parent has Madrid coords, reset Sofia's tutor doc to only Barcelona,
    and clean review/booking/notification state left by prior runs."""
    uid = parent_ctx["user"]["id"]
    # Reset Sofia's location to Barcelona only — prior test runs sometimes accumulate
    # extra locations (e.g. Madrid) which zero-out the distance metric.
    _db.tutors.update_one(
        {"name": "Sofía García"},
        {
            "$set": {
                "location": "Barcelona, ES",
                "latitude": 41.3874,
                "longitude": 2.1686,
                "locations": [
                    {"name": "Barcelona, ES", "latitude": 41.3874, "longitude": 2.1686}
                ],
                "allows_remote": True,
                "rating": 4.9,
                "reviews_count": 42,
            }
        },
    )
    # And Marie's canonical Lyon coords (in case of accidental drift)
    _db.tutors.update_one(
        {"name": "Marie Dubois"},
        {
            "$set": {
                "location": "Lyon, FR",
                "latitude": 45.7640,
                "longitude": 4.8357,
                "locations": [
                    {"name": "Lyon, FR", "latitude": 45.7640, "longitude": 4.8357}
                ],
                "allows_remote": False,
            }
        },
    )
    # Wipe reviews / test-injected bookings / review notifications this suite creates
    _db.reviews.delete_many({"parent_id": uid})
    _db.bookings.delete_many({"parent_id": uid, "notes": {"$regex": "^TEST_SESSION5"}})
    _db.notifications.delete_many({"user_id": uid, "kind": {"$regex": "^review:"}})
    # PATCH the parent's city to Madrid so coordinates are populated
    r = requests.patch(
        f"{BASE}/api/parents/me/profile",
        headers=_auth(parent_ctx["token"]),
        json={"city": "Madrid, ES"},
        timeout=20,
    )
    assert r.status_code == 200, f"patch profile failed: {r.status_code} {r.text}"
    prof = r.json()
    if prof.get("latitude") is None:
        # Try a larger, less-cache-flaky city as a fallback
        for fallback in ["Madrid, Spain", "Paris, FR", "New York, NY"]:
            r2 = requests.patch(
                f"{BASE}/api/parents/me/profile",
                headers=_auth(parent_ctx["token"]),
                json={"city": fallback},
                timeout=20,
            )
            if r2.status_code == 200 and r2.json().get("latitude") is not None:
                prof = r2.json()
                break
    assert (
        prof.get("latitude") is not None and prof.get("longitude") is not None
    ), f"geocoding failed to populate lat/lng: {prof}"
    yield
    # Teardown: leave bookings/reviews cleaned so this file is re-runnable
    _db.reviews.delete_many({"parent_id": uid})
    _db.bookings.delete_many({"parent_id": uid, "notes": {"$regex": "^TEST_SESSION5"}})
    _db.notifications.delete_many({"user_id": uid, "kind": {"$regex": "^review:"}})


# =======================================================================================
# 1) Distance filter
# =======================================================================================
class TestDistanceFilter:
    def test_a1_unauthenticated_ignores_max_miles(self, tutor_ids):
        r = requests.get(f"{BASE}/api/tutors", params={"max_miles": 50}, timeout=15)
        assert r.status_code == 200
        tutors = r.json()
        names = {t["name"] for t in tutors}
        assert "Sofía García" in names
        assert "Marie Dubois" in names
        # Unauthenticated caller has no parent coords → distance_miles must be None for all
        for t in tutors:
            assert t.get("distance_miles") is None, f"distance leaked when unauth: {t}"

    def test_a2_parent_unfiltered_gets_distance_populated(self, parent_ctx, tutor_ids):
        r = requests.get(
            f"{BASE}/api/tutors",
            headers=_auth(parent_ctx["token"]),
            timeout=15,
        )
        assert r.status_code == 200
        tutors = r.json()
        by_id = {t["id"]: t for t in tutors}
        assert tutor_ids["sofia"] in by_id
        assert tutor_ids["marie"] in by_id
        s = by_id[tutor_ids["sofia"]]
        m = by_id[tutor_ids["marie"]]
        assert isinstance(s["distance_miles"], (int, float))
        assert isinstance(m["distance_miles"], (int, float))
        # Sofia in Barcelona → ~316 mi from Madrid; Marie in Lyon → ~640 mi
        assert 200 < s["distance_miles"] < 500, f"unexpected sofia distance: {s['distance_miles']}"
        assert 400 < m["distance_miles"] < 900, f"unexpected marie distance: {m['distance_miles']}"

    def test_a3_max_miles_50_default_remote_keeps_sofia_only(self, parent_ctx, tutor_ids):
        r = requests.get(
            f"{BASE}/api/tutors",
            params={"max_miles": 50},
            headers=_auth(parent_ctx["token"]),
            timeout=15,
        )
        assert r.status_code == 200
        ids = {t["id"] for t in r.json()}
        # Sofia allows_remote=True (default include_remote=true) → stays
        assert tutor_ids["sofia"] in ids, "Sofia (remote-friendly) should stay when include_remote=true"
        # Marie allows_remote=False + distance > 50 → excluded
        assert tutor_ids["marie"] not in ids, "Marie (non-remote, >50mi) should be excluded"

    def test_a4_max_miles_50_include_remote_false_excludes_both(self, parent_ctx, tutor_ids):
        r = requests.get(
            f"{BASE}/api/tutors",
            params={"max_miles": 50, "include_remote": "false"},
            headers=_auth(parent_ctx["token"]),
            timeout=15,
        )
        assert r.status_code == 200
        ids = {t["id"] for t in r.json()}
        assert tutor_ids["sofia"] not in ids
        assert tutor_ids["marie"] not in ids

    def test_a5_max_miles_1000_includes_both(self, parent_ctx, tutor_ids):
        r = requests.get(
            f"{BASE}/api/tutors",
            params={"max_miles": 1000},
            headers=_auth(parent_ctx["token"]),
            timeout=15,
        )
        assert r.status_code == 200
        ids = {t["id"] for t in r.json()}
        assert tutor_ids["sofia"] in ids
        assert tutor_ids["marie"] in ids

    def test_a6_results_sorted_nearest_first(self, parent_ctx, tutor_ids):
        r = requests.get(
            f"{BASE}/api/tutors",
            headers=_auth(parent_ctx["token"]),
            timeout=15,
        )
        assert r.status_code == 200
        tutors = r.json()
        distances = [t["distance_miles"] for t in tutors if t.get("distance_miles") is not None]
        assert distances == sorted(distances), f"expected ascending distance sort, got {distances}"
        # Sofia (~316) should appear before Marie (~640) in the list
        order = [t["id"] for t in tutors]
        assert order.index(tutor_ids["sofia"]) < order.index(tutor_ids["marie"])


# =======================================================================================
# 2) Invitation-accept response → invitation.booking_id on parent thread
# =======================================================================================
class TestInvitationBookingId:
    def test_b1_accept_populates_booking_id_on_thread(self, parent_ctx, sofia_ctx, tutor_ids):
        # Pick a far-future date/time that we know is allowed to bypass availability check.
        # Reset Sofia's weekly_availability so the invitation slot check passes for any time.
        _db.tutors.update_one(
            {"id": tutor_ids["sofia"]}, {"$set": {"weekly_availability": {}}}
        )
        # Clean any stale invitations between sofia<->parent
        _db.messages.delete_many(
            {
                "from_user_id": sofia_ctx["user"]["id"],
                "to_user_id": parent_ctx["user"]["id"],
                "kind": "invitation",
            }
        )
        future_date = (datetime.now(timezone.utc).date() + timedelta(days=21)).isoformat()
        payload = {
            "to_user_id": parent_ctx["user"]["id"],
            "date": future_date,
            "time": "10:00",
            "duration_minutes": 60,
            "language": "Spanish",
            "price_cents": 3500,
            "note": "TEST_SESSION5 invite",
        }
        r = requests.post(
            f"{BASE}/api/messages/invitation",
            headers=_auth(sofia_ctx["token"]),
            json=payload,
            timeout=20,
        )
        assert r.status_code == 200, f"invite create failed: {r.status_code} {r.text}"
        msg = r.json()
        msg_id = msg["id"]
        assert msg.get("invitation", {}).get("status") == "pending"

        # Parent accepts
        ra = requests.post(
            f"{BASE}/api/messages/invitation/{msg_id}/accept",
            headers=_auth(parent_ctx["token"]),
            timeout=20,
        )
        assert ra.status_code == 200, f"accept failed: {ra.status_code} {ra.text}"
        booking = ra.json()
        assert booking["id"], "booking id missing on accept response"
        assert booking["payment_status"] == "pending"

        # Parent-visible thread must show the booking_id under invitation
        rt = requests.get(
            f"{BASE}/api/messages/thread/{sofia_ctx['user']['id']}",
            headers=_auth(parent_ctx["token"]),
            timeout=15,
        )
        assert rt.status_code == 200, f"thread fetch failed: {rt.status_code} {rt.text}"
        thread = rt.json()
        inv_msg = next((m for m in thread if m.get("id") == msg_id), None)
        assert inv_msg is not None, "invitation not visible on parent thread"
        assert inv_msg.get("invitation", {}).get("status") == "accepted"
        assert (
            inv_msg["invitation"].get("booking_id") == booking["id"]
        ), f"booking_id not populated on invitation: {inv_msg['invitation']}"

        # Cleanup: cancel booking so it doesn't affect future runs
        _db.bookings.delete_one({"id": booking["id"]})
        _db.messages.delete_one({"id": msg_id})


# =======================================================================================
# 3) Reviews
# =======================================================================================
def _inject_past_paid_booking(parent_uid: str, parent_name: str, tutor_doc: dict, note_tag: str, ended_minutes_ago: int = 90):
    """Insert a paid booking whose (date, time) is `ended_minutes_ago` minutes in the past.
    Returns the booking dict."""
    booking_end = datetime.now(timezone.utc) - timedelta(minutes=ended_minutes_ago)
    duration = 60
    booking_start = booking_end - timedelta(minutes=duration)
    booking = {
        "id": str(uuid.uuid4()),
        "parent_id": parent_uid,
        "parent_name": parent_name,
        "tutor_id": tutor_doc["id"],
        "tutor_name": tutor_doc["name"],
        "date": booking_start.date().isoformat(),
        "time": f"{booking_start.hour:02d}:{booking_start.minute:02d}",
        "duration_minutes": duration,
        "language": "Spanish",
        "amount_cents": 3535,
        "platform_fee_cents": 35,
        "currency": tutor_doc.get("currency", "usd"),
        "payment_status": "paid",
        "stripe_payment_intent_id": f"pi_mock_{uuid.uuid4()}",
        "client_secret": None,
        "notes": note_tag,
        "is_au_pair": False,
        "lessons_count": 1,
        "distance_miles": None,
        "remote": True,
        "created_at": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
    }
    _db.bookings.insert_one(dict(booking))
    return booking


class TestReviews:
    def test_c1_post_review_and_get_returns_booking_id(self, parent_ctx, sofia_ctx, tutor_ids):
        uid = parent_ctx["user"]["id"]
        # Wipe reviews so rolling average starts from Sofia's seeded 4.9/42
        _db.reviews.delete_many({"parent_id": uid})
        # Capture Sofia's pre-review rating snapshot (seed constants)
        _db.tutors.update_one(
            {"id": tutor_ids["sofia"]},
            {"$set": {"rating": 4.9, "reviews_count": 42}},
        )
        booking = _inject_past_paid_booking(
            uid, parent_ctx["user"]["name"], tutor_ids["sofia_doc"], "TEST_SESSION5_review"
        )
        payload = {
            "tutor_id": tutor_ids["sofia"],
            "booking_id": booking["id"],
            "rating": 5,
            "comment": "Great session — session-5 test",
        }
        r = requests.post(
            f"{BASE}/api/reviews",
            headers=_auth(parent_ctx["token"]),
            json=payload,
            timeout=15,
        )
        assert r.status_code == 200, f"POST review failed: {r.status_code} {r.text}"
        rev = r.json()
        assert rev["booking_id"] == booking["id"]
        assert rev["rating"] == 5
        assert rev["tutor_id"] == tutor_ids["sofia"]

        # GET /api/reviews/tutor/{id} must include this review with booking_id
        rg = requests.get(f"{BASE}/api/reviews/tutor/{tutor_ids['sofia']}", timeout=15)
        assert rg.status_code == 200
        reviews = rg.json()
        match = next((x for x in reviews if x["id"] == rev["id"]), None)
        assert match is not None, "new review missing from GET /reviews/tutor"
        assert match["booking_id"] == booking["id"]
        assert match["rating"] == 5

        # tutors.rating / reviews_count reflect rolling average
        # Only our own review is in the DB (we deleted others), so avg=5.0 count=1
        tutor_after = _db.tutors.find_one({"id": tutor_ids["sofia"]}, {"_id": 0})
        assert tutor_after["reviews_count"] == 1, f"expected 1 review, got {tutor_after['reviews_count']}"
        assert tutor_after["rating"] == 5.0, f"expected avg 5.0, got {tutor_after['rating']}"

        # A second review of the SAME booking is rejected (one review per session).
        dup = requests.post(
            f"{BASE}/api/reviews",
            headers=_auth(parent_ctx["token"]),
            json={**payload, "rating": 1, "comment": "duplicate"},
            timeout=15,
        )
        assert dup.status_code == 409, f"duplicate review should be 409, got {dup.status_code}"

        # A 3-star review of a second session validates the rolling-average math.
        booking2 = _inject_past_paid_booking(
            uid, parent_ctx["user"]["name"], tutor_ids["sofia_doc"], "TEST_SESSION5_review2"
        )
        payload2 = {
            "tutor_id": tutor_ids["sofia"],
            "booking_id": booking2["id"],
            "rating": 3,
            "comment": "Second sample",
        }
        r2 = requests.post(
            f"{BASE}/api/reviews",
            headers=_auth(parent_ctx["token"]),
            json=payload2,
            timeout=15,
        )
        assert r2.status_code == 200
        tutor_after2 = _db.tutors.find_one({"id": tutor_ids["sofia"]}, {"_id": 0})
        assert tutor_after2["reviews_count"] == 2
        assert tutor_after2["rating"] == 4.0, f"expected avg 4.0, got {tutor_after2['rating']}"


# =======================================================================================
# 4) _generate_dynamic_notifications — review:<booking_id>
# =======================================================================================
class TestReviewNotifications:
    def test_d1_review_notification_created_when_no_review(self, parent_ctx, tutor_ids):
        uid = parent_ctx["user"]["id"]
        # Fresh slate for this scenario
        _db.reviews.delete_many({"parent_id": uid})
        _db.bookings.delete_many({"parent_id": uid, "notes": {"$regex": "^TEST_SESSION5"}})
        _db.notifications.delete_many({"user_id": uid, "kind": {"$regex": "^review:"}})

        booking = _inject_past_paid_booking(
            uid, parent_ctx["user"]["name"], tutor_ids["sofia_doc"], "TEST_SESSION5_notif"
        )
        # Hit notifications — should trigger review:<id>
        rn = requests.get(
            f"{BASE}/api/notifications",
            headers=_auth(parent_ctx["token"]),
            timeout=15,
        )
        assert rn.status_code == 200
        notifs = rn.json()
        review_notif = next(
            (n for n in notifs if n["kind"] == f"review:{booking['id']}"), None
        )
        assert (
            review_notif is not None
        ), f"review notification for {booking['id']} missing; got kinds={[n['kind'] for n in notifs]}"
        assert "How was your session" in review_notif["title"]

    def test_d2_review_notification_suppressed_when_review_exists(self, parent_ctx, tutor_ids):
        uid = parent_ctx["user"]["id"]
        _db.reviews.delete_many({"parent_id": uid})
        _db.bookings.delete_many({"parent_id": uid, "notes": {"$regex": "^TEST_SESSION5"}})
        _db.notifications.delete_many({"user_id": uid, "kind": {"$regex": "^review:"}})

        booking = _inject_past_paid_booking(
            uid, parent_ctx["user"]["name"], tutor_ids["sofia_doc"], "TEST_SESSION5_notif_skip"
        )
        # Insert a review directly (mimics parent already having rated)
        _db.reviews.insert_one(
            {
                "id": str(uuid.uuid4()),
                "tutor_id": tutor_ids["sofia"],
                "booking_id": booking["id"],
                "parent_id": uid,
                "parent_name": parent_ctx["user"]["name"],
                "rating": 5,
                "comment": "already rated",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        rn = requests.get(
            f"{BASE}/api/notifications",
            headers=_auth(parent_ctx["token"]),
            timeout=15,
        )
        assert rn.status_code == 200
        notifs = rn.json()
        review_notif = next(
            (n for n in notifs if n["kind"] == f"review:{booking['id']}"), None
        )
        assert (
            review_notif is None
        ), f"review notification should NOT be created when a review already exists: {review_notif}"
