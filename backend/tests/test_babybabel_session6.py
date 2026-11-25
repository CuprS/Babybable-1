"""
Session-6 backend feature tests for Babybabel:

1) housing_offered on POST /api/bookings — persisted only when is_au_pair=true;
   otherwise stored as "". Round-trips on GET /api/bookings/{id} and
   GET /api/bookings/me. >800 chars → 422. Missing → defaults to "".

2) Morning-of reminder in _generate_dynamic_notifications — fires ONCE per
   booking (dedupe on kind) when a paid booking is TODAY (same UTC date) and
   >10 min in the future. Non-today / past bookings do NOT trigger it. The
   existing 2-hour `reminder:<id>` still fires alongside `morning:<id>` when the
   session is within 2h.

The suite is idempotent: cleans stale docs before/after via pymongo and does not
mutate seeded tutor availability outside its own scope.
"""
import os
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

NOTE_TAG = "TEST_SESSION6"


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
    sofia = _db.tutors.find_one({"user_id": sofia_ctx["user"]["id"]}, {"_id": 0})
    assert sofia, "Sofia tutor doc missing"
    return {"sofia": sofia["id"], "sofia_doc": sofia}


@pytest.fixture(scope="module", autouse=True)
def _setup(parent_ctx, tutor_ids):
    """Pin Sofia's location + open all slots; ensure parent has coords; clean test bookings."""
    uid = parent_ctx["user"]["id"]
    _db.tutors.update_one(
        {"id": tutor_ids["sofia"]},
        {
            "$set": {
                "location": "Barcelona, ES",
                "latitude": 41.3874,
                "longitude": 2.1686,
                "locations": [
                    {"name": "Barcelona, ES", "latitude": 41.3874, "longitude": 2.1686}
                ],
                "allows_remote": True,
                "weekly_availability": {},  # empty = legacy = accept any slot
            }
        },
    )
    # Clean stale test bookings + notifications
    _db.bookings.delete_many({"parent_id": uid, "notes": {"$regex": f"^{NOTE_TAG}"}})
    _db.notifications.delete_many(
        {"user_id": uid, "kind": {"$regex": "^(morning|reminder|review):"}}
    )
    # Ensure parent has coords (Madrid). Falls back if geocoding flakes.
    r = requests.patch(
        f"{BASE}/api/parents/me/profile",
        headers=_auth(parent_ctx["token"]),
        json={"city": "Barcelona, ES"},
        timeout=20,
    )
    assert r.status_code == 200, f"patch profile failed: {r.status_code} {r.text}"
    prof = r.json()
    if prof.get("latitude") is None:
        for fallback in ["Madrid, ES", "Madrid, Spain", "Paris, FR", "New York, NY"]:
            r2 = requests.patch(
                f"{BASE}/api/parents/me/profile",
                headers=_auth(parent_ctx["token"]),
                json={"city": fallback},
                timeout=20,
            )
            if r2.status_code == 200 and r2.json().get("latitude") is not None:
                prof = r2.json()
                break
    # Not strictly required for au-pair, but useful for the non-au-pair single-session test.
    yield
    # Teardown
    _db.bookings.delete_many({"parent_id": uid, "notes": {"$regex": f"^{NOTE_TAG}"}})
    _db.notifications.delete_many(
        {"user_id": uid, "kind": {"$regex": "^(morning|reminder|review):"}}
    )


def _future_date_time(days_ahead: int = 14, hh: str = "10:00"):
    d = (datetime.now(timezone.utc).date() + timedelta(days=days_ahead)).isoformat()
    return d, hh


def _inject_paid_booking(
    parent_uid: str,
    parent_name: str,
    tutor_doc: dict,
    when: datetime,
    duration: int = 60,
    note_tag: str = NOTE_TAG,
    is_au_pair: bool = False,
):
    """Insert a paid booking at the given UTC datetime, bypassing slot checks."""
    when = when.astimezone(timezone.utc)
    booking = {
        "id": str(uuid.uuid4()),
        "parent_id": parent_uid,
        "parent_name": parent_name,
        "tutor_id": tutor_doc["id"],
        "tutor_name": tutor_doc["name"],
        "date": when.date().isoformat(),
        "time": f"{when.hour:02d}:{when.minute:02d}",
        "duration_minutes": duration,
        "language": "Spanish",
        "amount_cents": 3535,
        "platform_fee_cents": 35,
        "currency": tutor_doc.get("currency", "usd"),
        "payment_status": "paid",
        "stripe_payment_intent_id": f"pi_mock_{uuid.uuid4()}",
        "client_secret": None,
        "notes": note_tag,
        "is_au_pair": is_au_pair,
        "lessons_count": 30 if is_au_pair else 1,
        "distance_miles": None,
        "remote": not is_au_pair,
        "housing_offered": "",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _db.bookings.insert_one(dict(booking))
    return booking


# =======================================================================================
# 1) housing_offered
# =======================================================================================
class TestHousingOffered:
    def test_a1_non_au_pair_discards_housing(self, parent_ctx, tutor_ids):
        # Book single-session (non au-pair). Sofia is allows_remote=True → passes.
        date, tm = _future_date_time(days_ahead=14, hh="10:00")
        payload = {
            "tutor_id": tutor_ids["sofia"],
            "date": date,
            "time": tm,
            "duration_minutes": 60,
            "language": "Spanish",
            "notes": f"{NOTE_TAG}_a1",
            "is_au_pair": False,
            "lessons_count": 1,
            "housing_offered": "private room",
        }
        r = requests.post(
            f"{BASE}/api/bookings",
            headers=_auth(parent_ctx["token"]),
            json=payload,
            timeout=20,
        )
        assert r.status_code == 200, f"POST /bookings failed: {r.status_code} {r.text}"
        b = r.json()
        assert "housing_offered" in b, "housing_offered missing from Booking response"
        assert (
            b["housing_offered"] == ""
        ), f"housing_offered must be '' for non-au-pair, got {b['housing_offered']!r}"

        # GET /api/bookings/{id}
        rg = requests.get(
            f"{BASE}/api/bookings/{b['id']}",
            headers=_auth(parent_ctx["token"]),
            timeout=15,
        )
        assert rg.status_code == 200
        assert rg.json()["housing_offered"] == ""

    def test_a2_au_pair_persists_housing_roundtrip(self, parent_ctx, tutor_ids):
        date, tm = _future_date_time(days_ahead=25, hh="09:00")
        housing = "Private ensuite, meals included, one friendly dog"
        payload = {
            "tutor_id": tutor_ids["sofia"],
            "date": date,
            "time": tm,
            "duration_minutes": 60,
            "language": "Spanish",
            "notes": f"{NOTE_TAG}_a2",
            "is_au_pair": True,
            "lessons_count": 30,
            "housing_offered": housing,
        }
        r = requests.post(
            f"{BASE}/api/bookings",
            headers=_auth(parent_ctx["token"]),
            json=payload,
            timeout=20,
        )
        assert r.status_code == 200, f"au-pair POST failed: {r.status_code} {r.text}"
        b = r.json()
        assert b["is_au_pair"] is True
        assert b["housing_offered"] == housing, (
            f"housing_offered mismatch: got {b['housing_offered']!r}"
        )

        # GET /api/bookings/{id} still returns it
        rg = requests.get(
            f"{BASE}/api/bookings/{b['id']}",
            headers=_auth(parent_ctx["token"]),
            timeout=15,
        )
        assert rg.status_code == 200
        assert rg.json()["housing_offered"] == housing

        # GET /api/bookings/me includes it
        rm = requests.get(
            f"{BASE}/api/bookings/me",
            headers=_auth(parent_ctx["token"]),
            timeout=15,
        )
        assert rm.status_code == 200
        bookings = rm.json()
        match = next((x for x in bookings if x["id"] == b["id"]), None)
        assert match is not None, "au-pair booking missing from GET /bookings/me"
        assert match["housing_offered"] == housing

    def test_a3_over_800_chars_returns_422(self, parent_ctx, tutor_ids):
        date, tm = _future_date_time(days_ahead=27, hh="11:00")
        payload = {
            "tutor_id": tutor_ids["sofia"],
            "date": date,
            "time": tm,
            "duration_minutes": 60,
            "language": "Spanish",
            "notes": f"{NOTE_TAG}_a3",
            "is_au_pair": True,
            "lessons_count": 30,
            "housing_offered": "x" * 801,
        }
        r = requests.post(
            f"{BASE}/api/bookings",
            headers=_auth(parent_ctx["token"]),
            json=payload,
            timeout=20,
        )
        assert (
            r.status_code == 422
        ), f"expected 422 for >800 chars, got {r.status_code}: {r.text}"

    def test_a4_missing_housing_defaults_to_empty(self, parent_ctx, tutor_ids):
        date, tm = _future_date_time(days_ahead=28, hh="12:00")
        # No housing_offered key at all
        payload = {
            "tutor_id": tutor_ids["sofia"],
            "date": date,
            "time": tm,
            "duration_minutes": 60,
            "language": "Spanish",
            "notes": f"{NOTE_TAG}_a4",
            "is_au_pair": True,
            "lessons_count": 30,
        }
        r = requests.post(
            f"{BASE}/api/bookings",
            headers=_auth(parent_ctx["token"]),
            json=payload,
            timeout=20,
        )
        assert r.status_code == 200, f"missing housing rejected: {r.status_code} {r.text}"
        assert r.json()["housing_offered"] == ""


# =======================================================================================
# 2) Morning-of reminder
# =======================================================================================
class TestMorningReminder:
    def _clean_notifs(self, uid):
        _db.notifications.delete_many(
            {"user_id": uid, "kind": {"$regex": "^(morning|reminder|review):"}}
        )

    def test_b1_morning_notif_created_and_idempotent(self, parent_ctx, tutor_ids):
        uid = parent_ctx["user"]["id"]
        self._clean_notifs(uid)
        # Pick a time TODAY that is >20min in the future.
        now = datetime.now(timezone.utc)
        target = now + timedelta(hours=4)
        # Guard: if today's date rolls over within 4h (unlikely at test time), clamp.
        if target.date() != now.date():
            # Use now + 30 min, still same day and > 10min in future
            target = now + timedelta(minutes=30)
            assert target.date() == now.date(), "clock crossed midnight, test skipped"

        b = _inject_paid_booking(
            uid, parent_ctx["user"]["name"], tutor_ids["sofia_doc"], target
        )

        # Hit notifications endpoint
        rn = requests.get(
            f"{BASE}/api/notifications",
            headers=_auth(parent_ctx["token"]),
            timeout=15,
        )
        assert rn.status_code == 200
        notifs = rn.json()
        morning = [n for n in notifs if n["kind"] == f"morning:{b['id']}"]
        assert len(morning) == 1, (
            f"expected 1 morning notif, got {len(morning)}; kinds={[n['kind'] for n in notifs]}"
        )
        m = morning[0]
        assert m["title"].startswith("Session today at"), f"unexpected title: {m['title']!r}"
        assert (
            tutor_ids["sofia_doc"]["name"] in m["body"]
        ), f"tutor name missing from body: {m['body']!r}"

        # Second GET → still exactly one (idempotency guard)
        rn2 = requests.get(
            f"{BASE}/api/notifications",
            headers=_auth(parent_ctx["token"]),
            timeout=15,
        )
        assert rn2.status_code == 200
        morning2 = [n for n in rn2.json() if n["kind"] == f"morning:{b['id']}"]
        assert len(morning2) == 1, f"morning notif duplicated on 2nd GET: {len(morning2)}"

    def test_b2_future_non_today_no_morning(self, parent_ctx, tutor_ids):
        uid = parent_ctx["user"]["id"]
        self._clean_notifs(uid)
        target = datetime.now(timezone.utc) + timedelta(days=3, hours=2)
        b = _inject_paid_booking(
            uid, parent_ctx["user"]["name"], tutor_ids["sofia_doc"], target
        )
        rn = requests.get(
            f"{BASE}/api/notifications",
            headers=_auth(parent_ctx["token"]),
            timeout=15,
        )
        assert rn.status_code == 200
        morning = [n for n in rn.json() if n["kind"] == f"morning:{b['id']}"]
        assert (
            not morning
        ), f"non-today booking should NOT create morning notif: {morning}"

    def test_b3_past_booking_no_morning(self, parent_ctx, tutor_ids):
        uid = parent_ctx["user"]["id"]
        self._clean_notifs(uid)
        # 15 minutes in the past → delta_min < 10 → guard fails
        target = datetime.now(timezone.utc) - timedelta(minutes=15)
        b = _inject_paid_booking(
            uid, parent_ctx["user"]["name"], tutor_ids["sofia_doc"], target
        )
        rn = requests.get(
            f"{BASE}/api/notifications",
            headers=_auth(parent_ctx["token"]),
            timeout=15,
        )
        assert rn.status_code == 200
        morning = [n for n in rn.json() if n["kind"] == f"morning:{b['id']}"]
        assert (
            not morning
        ), f"past booking (10+min ago) should NOT create morning notif: {morning}"

    def test_b4_morning_and_reminder_both_fire_within_2h(self, parent_ctx, tutor_ids):
        uid = parent_ctx["user"]["id"]
        self._clean_notifs(uid)
        # 60 min from now → same-day + within 2h → both morning:<id> AND reminder:<id>
        now = datetime.now(timezone.utc)
        target = now + timedelta(minutes=60)
        if target.date() != now.date():
            pytest.skip("test straddles midnight UTC")

        b = _inject_paid_booking(
            uid, parent_ctx["user"]["name"], tutor_ids["sofia_doc"], target
        )
        rn = requests.get(
            f"{BASE}/api/notifications",
            headers=_auth(parent_ctx["token"]),
            timeout=15,
        )
        assert rn.status_code == 200
        notifs = rn.json()
        morning = [n for n in notifs if n["kind"] == f"morning:{b['id']}"]
        reminder = [n for n in notifs if n["kind"] == f"reminder:{b['id']}"]
        assert len(morning) == 1, f"expected 1 morning notif, got {len(morning)}"
        assert len(reminder) == 1, f"expected 1 reminder notif, got {len(reminder)}"
