"""
Backend regression + new-feature tests for the Babybabel session-4 changes:

1) Auth hardening — min password length, generic duplicate signup, login rate-limit
2) Weekly availability — PATCH /tutors/me/profile normalization + empty-day pruning
3) GET /tutors/{id}/booked-slots
4) Booking slot enforcement (availability + double-booking, au-pair bypass)
5) 1% platform fee — amount_cents math, /admin/earnings ledger, idempotent confirm-mock,
   /admin/stats exposes platform_earnings_cents + platform_earnings_count
6) Invitation slot enforcement — outside availability (400) / already-booked (409)

Ordering rules:
 - The login rate-limit test is LAST because it will burn the 8/300s bucket for our IP.
 - Signup rate-limit budget is 5/600s — we only spend 1 real signup call in this suite
   (the <8-char signup returns 422 from Pydantic BEFORE the rate_limit call, so it does
   not consume a token).
"""
import os
import uuid
import time
import pytest
import requests
import pymongo
from datetime import datetime, timedelta, timezone
from pathlib import Path
from dotenv import load_dotenv
from _support import admin_credentials, admin_session  # noqa: E402

# Load backend .env so we can talk to Mongo directly for setup/teardown of stale test data.
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

BASE = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "http://localhost:8001").rstrip("/")
_mongo = pymongo.MongoClient(os.environ["MONGO_URL"])
_db = _mongo[os.environ["DB_NAME"]]

SOFIA_EMAIL = "sofia@babybabel.dev"
SOFIA_PW = "password123"
PARENT_EMAIL = "parent@test.dev"
PARENT_PW = "password123"


def next_monday_iso():
    today = datetime.now(timezone.utc).date()
    days_ahead = (0 - today.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return (today + timedelta(days=days_ahead)).isoformat()


def _login(email, password):
    r = requests.post(f"{BASE}/api/auth/login", json={"email": email, "password": password}, timeout=15)
    return r


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# -------- Shared fixtures (session-scoped so we only spend one login per role) --------

@pytest.fixture(scope="session")
def sofia_token():
    r = _login(SOFIA_EMAIL, SOFIA_PW)
    assert r.status_code == 200, f"Sofia login failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def parent_token():
    # Try to log in; if the seed parent has been wiped, create a fresh one.
    r = _login(PARENT_EMAIL, PARENT_PW)
    if r.status_code != 200:
        rs = requests.post(
            f"{BASE}/api/auth/signup",
            json={"email": PARENT_EMAIL, "password": PARENT_PW, "name": "Parent Test", "role": "parent"},
            timeout=15,
        )
        assert rs.status_code in (201, 400), f"parent signup unexpected: {rs.status_code} {rs.text}"
        r = _login(PARENT_EMAIL, PARENT_PW)
    assert r.status_code == 200, f"Parent login failed: {r.status_code} {r.text}"
    tok = r.json()["access_token"]
    # Make sure the parent has a city (needed for the distance check on non-remote tutors,
    # though Sofia allows_remote=True so distance is bypassed — set it anyway for safety).
    requests.patch(f"{BASE}/api/parents/me/profile", headers=_auth(tok), json={"city": "Barcelona, ES"}, timeout=15)
    return tok


@pytest.fixture(scope="session")
def admin_token():
    return admin_session()["access_token"]


@pytest.fixture(scope="session")
def sofia_tutor_id(sofia_token):
    r = requests.get(f"{BASE}/api/tutors/me/profile", headers=_auth(sofia_token), timeout=15)
    assert r.status_code == 200
    return r.json()["id"]


@pytest.fixture(scope="session", autouse=True)
def _scrub_stale_test_data(sofia_tutor_id):
    """Delete lingering test bookings from prior runs for Sofia on next-Monday at the
    two slots this suite uses (07:00 and 10:00), plus their platform_earnings entries.
    This is idempotent and safe — real bookings by real users would have distinct dates."""
    monday = next_monday_iso()
    stale = list(_db.bookings.find(
        {"tutor_id": sofia_tutor_id, "date": monday, "time": {"$in": ["10:00", "07:00"]}},
        {"_id": 0, "id": 1},
    ))
    ids = [b["id"] for b in stale]
    if ids:
        _db.platform_earnings.delete_many({"booking_id": {"$in": ids}})
        _db.bookings.delete_many({"id": {"$in": ids}})
    yield


@pytest.fixture(scope="session")
def parent_user_id(parent_token):
    r = requests.get(f"{BASE}/api/auth/me", headers=_auth(parent_token), timeout=15)
    assert r.status_code == 200
    return r.json()["id"]


# ============================================================
# 2) Weekly availability (must run BEFORE booking tests)
# ============================================================

class TestAvailability:

    def test_a1_set_availability_and_normalize(self, sofia_token):
        monday_iso = next_monday_iso()
        body = {"weekly_availability": {"mon": ["09:00", "10:00"], "tue": ["09:00"]}}
        r = requests.patch(f"{BASE}/api/tutors/me/profile", headers=_auth(sofia_token), json=body, timeout=15)
        assert r.status_code == 200, r.text
        # Re-read
        r = requests.get(f"{BASE}/api/tutors/me/profile", headers=_auth(sofia_token), timeout=15)
        assert r.status_code == 200
        wa = r.json()["weekly_availability"]
        assert wa == {"mon": ["09:00", "10:00"], "tue": ["09:00"]}, wa
        assert monday_iso  # sanity

    def test_a2_unnormalized_input(self, sofia_token):
        body = {"weekly_availability": {"mon": ["9:00", "10:00", "bogus"], "tue": ["09:00"]}}
        r = requests.patch(f"{BASE}/api/tutors/me/profile", headers=_auth(sofia_token), json=body, timeout=15)
        assert r.status_code == 200, r.text
        wa = r.json()["weekly_availability"]
        assert wa.get("mon") == ["09:00", "10:00"], wa
        assert "bogus" not in str(wa)

    def test_a3_empty_day_arrays_are_removed(self, sofia_token):
        body = {"weekly_availability": {"mon": ["09:00", "10:00"], "tue": ["09:00"], "wed": []}}
        r = requests.patch(f"{BASE}/api/tutors/me/profile", headers=_auth(sofia_token), json=body, timeout=15)
        assert r.status_code == 200, r.text
        wa = r.json()["weekly_availability"]
        assert "wed" not in wa, wa
        assert set(wa.keys()) == {"mon", "tue"}, wa


# ============================================================
# 3-5) Bookings + slots + platform fee
# ============================================================

class TestBookingsAndFee:
    """Ordered scenario: fresh parent account so we don't collide with pre-existing bookings."""

    @pytest.fixture(scope="class")
    def fresh_parent(self):
        # Use a fresh parent to avoid duplicate-slot collisions from prior test runs.
        email = f"TEST_parent_s4_{uuid.uuid4().hex[:8]}@test.dev"
        pw = "password123"
        rs = requests.post(
            f"{BASE}/api/auth/signup",
            json={"email": email, "password": pw, "name": "S4 Parent", "role": "parent"},
            timeout=15,
        )
        assert rs.status_code == 201, f"signup: {rs.status_code} {rs.text}"
        tok = rs.json()["access_token"]
        uid = rs.json()["user"]["id"]
        # Set city so distance rules pass on non-remote tutors (Sofia allows_remote=True but be safe)
        requests.patch(f"{BASE}/api/parents/me/profile", headers=_auth(tok), json={"city": "Barcelona, ES"}, timeout=15)
        return {"token": tok, "id": uid, "email": email}

    def test_b0_availability_precondition(self, sofia_token):
        # Make sure Sofia has mon 09:00 & 10:00 (idempotent).
        body = {"weekly_availability": {"mon": ["09:00", "10:00"], "tue": ["09:00"]}}
        r = requests.patch(f"{BASE}/api/tutors/me/profile", headers=_auth(sofia_token), json=body, timeout=15)
        assert r.status_code == 200

    def test_b1_booking_at_unavailable_time_400(self, fresh_parent, sofia_tutor_id):
        monday = next_monday_iso()
        payload = {
            "tutor_id": sofia_tutor_id, "date": monday, "time": "07:00",
            "duration_minutes": 60, "language": "Spanish", "notes": "test", "is_au_pair": False,
        }
        r = requests.post(f"{BASE}/api/bookings", headers=_auth(fresh_parent["token"]), json=payload, timeout=15)
        assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"
        assert "isn't available" in r.text or "available" in r.text.lower()

    def test_b2_booking_succeeds_with_fee(self, fresh_parent, sofia_tutor_id):
        monday = next_monday_iso()
        payload = {
            "tutor_id": sofia_tutor_id, "date": monday, "time": "10:00",
            "duration_minutes": 60, "language": "Spanish", "notes": "test", "is_au_pair": False,
        }
        r = requests.post(f"{BASE}/api/bookings", headers=_auth(fresh_parent["token"]), json=payload, timeout=15)
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        b = r.json()
        assert b["platform_fee_cents"] == 35, b
        assert b["amount_cents"] == 3535, b
        assert b["duration_minutes"] == 60
        assert b["payment_status"] == "pending"
        # Stash the booking for follow-up tests.
        pytest.session4_booking = b

    def test_b3_booked_slots_reflects_it(self, sofia_tutor_id):
        monday = next_monday_iso()
        r = requests.get(f"{BASE}/api/tutors/{sofia_tutor_id}/booked-slots", timeout=15)
        assert r.status_code == 200
        rows = r.json()
        assert isinstance(rows, list)
        assert any(row["date"] == monday and row["time"] == "10:00" for row in rows), rows

    def test_b4_double_booking_returns_409(self, fresh_parent, sofia_tutor_id):
        monday = next_monday_iso()
        payload = {
            "tutor_id": sofia_tutor_id, "date": monday, "time": "10:00",
            "duration_minutes": 60, "language": "Spanish", "is_au_pair": False,
        }
        r = requests.post(f"{BASE}/api/bookings", headers=_auth(fresh_parent["token"]), json=payload, timeout=15)
        assert r.status_code == 409, f"{r.status_code} {r.text}"

    def test_b5_au_pair_skips_slot_checks(self, fresh_parent, sofia_tutor_id):
        # 07:00 is NOT in Sofia's calendar; au-pair should bypass the check.
        monday = next_monday_iso()
        payload = {
            "tutor_id": sofia_tutor_id, "date": monday, "time": "07:00",
            "duration_minutes": 60, "language": "Spanish",
            "is_au_pair": True, "lessons_count": 30,
        }
        r = requests.post(f"{BASE}/api/bookings", headers=_auth(fresh_parent["token"]), json=payload, timeout=15)
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        assert r.json()["is_au_pair"] is True

    def test_b6_confirm_mock_credits_platform_earnings(self, fresh_parent, admin_token):
        b = getattr(pytest, "session4_booking", None)
        assert b, "prior booking fixture missing"
        # Baseline
        r0 = requests.get(f"{BASE}/api/admin/earnings", headers=_auth(admin_token), timeout=15)
        assert r0.status_code == 200
        baseline_total = r0.json()["total_cents"]
        baseline_count = r0.json()["count"]

        r = requests.post(f"{BASE}/api/bookings/{b['id']}/confirm-mock", headers=_auth(fresh_parent["token"]), timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["payment_status"] == "paid"

        r1 = requests.get(f"{BASE}/api/admin/earnings", headers=_auth(admin_token), timeout=15)
        assert r1.status_code == 200
        j = r1.json()
        assert j["total_cents"] == baseline_total + 35, (baseline_total, j["total_cents"])
        assert j["count"] == baseline_count + 1, (baseline_count, j["count"])
        # And the entry should reference our booking
        assert any(e.get("booking_id") == b["id"] and e.get("amount_cents") == 35 for e in j["entries"]), j["entries"][:3]

    def test_b7_confirm_mock_is_idempotent(self, fresh_parent, admin_token):
        b = getattr(pytest, "session4_booking", None)
        assert b
        r_before = requests.get(f"{BASE}/api/admin/earnings", headers=_auth(admin_token), timeout=15)
        cnt_before = r_before.json()["count"]
        total_before = r_before.json()["total_cents"]
        # Second confirm-mock call — should NOT create a duplicate earnings entry.
        r = requests.post(f"{BASE}/api/bookings/{b['id']}/confirm-mock", headers=_auth(fresh_parent["token"]), timeout=15)
        assert r.status_code == 200
        r_after = requests.get(f"{BASE}/api/admin/earnings", headers=_auth(admin_token), timeout=15)
        assert r_after.json()["count"] == cnt_before, "idempotency violated"
        assert r_after.json()["total_cents"] == total_before

    def test_b8_admin_stats_has_earnings_fields(self, admin_token):
        r = requests.get(f"{BASE}/api/admin/stats", headers=_auth(admin_token), timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        assert "platform_earnings_cents" in j, j
        assert "platform_earnings_count" in j, j
        assert j["platform_earnings_cents"] >= 35
        assert j["platform_earnings_count"] >= 1


# ============================================================
# 6) Invitation slot enforcement
# ============================================================

class TestInvitationEnforcement:

    def test_i1_outside_availability_returns_400(self, sofia_token, parent_user_id):
        # 07:00 is NOT in Sofia's mon calendar
        monday = next_monday_iso()
        payload = {
            "to_user_id": parent_user_id,
            "price_cents": 3000, "date": monday, "time": "07:00",
            "duration_minutes": 60, "language": "Spanish", "note": "t"
        }
        r = requests.post(f"{BASE}/api/messages/invitation", headers=_auth(sofia_token), json=payload, timeout=15)
        assert r.status_code == 400, f"{r.status_code} {r.text}"
        assert "outside your weekly availability" in r.text.lower()

    def test_i2_already_booked_slot_returns_409(self, sofia_token, parent_user_id):
        # Monday 10:00 was booked in TestBookingsAndFee.
        monday = next_monday_iso()
        payload = {
            "to_user_id": parent_user_id,
            "price_cents": 3000, "date": monday, "time": "10:00",
            "duration_minutes": 60, "language": "Spanish", "note": "t"
        }
        r = requests.post(f"{BASE}/api/messages/invitation", headers=_auth(sofia_token), json=payload, timeout=15)
        assert r.status_code == 409, f"{r.status_code} {r.text}"


# ============================================================
# 1) Auth hardening
#    -> signup validation (<8 chars => 422) is fired by Pydantic BEFORE rate_limit,
#       so it doesn't burn a signup token.
#    -> The generic-duplicate check DOES burn one signup token.
#    -> The rate-limit test is LAST so subsequent tests aren't blocked.
# ============================================================

class TestAuthHardening:

    def test_c1_password_too_short_returns_422(self):
        r = requests.post(
            f"{BASE}/api/auth/signup",
            json={"email": f"TEST_short_{uuid.uuid4().hex[:6]}@test.dev", "password": "abc", "name": "X", "role": "parent"},
            timeout=15,
        )
        assert r.status_code == 422, f"{r.status_code} {r.text}"

    def test_c2_duplicate_email_generic_error(self):
        # sofia is a known existing user
        r = requests.post(
            f"{BASE}/api/auth/signup",
            json={"email": SOFIA_EMAIL, "password": "password123", "name": "dup", "role": "parent"},
            timeout=15,
        )
        assert r.status_code == 400, f"{r.status_code} {r.text}"
        detail = (r.json().get("detail") or "").lower()
        assert "already registered" not in detail, f"leak: {detail}"
        assert "couldn't create" in detail or "different email" in detail or "try logging in" in detail, detail

    def test_c3_login_still_works_before_ratelimit(self):
        r = _login(PARENT_EMAIL, PARENT_PW)
        # Either 200 (works) OR 401 (parent doesn't exist yet — fresh env) is acceptable
        # here because parent_token fixture recreates the account.
        # But we've already used parent_token fixture, so parent should exist.
        assert r.status_code in (200, 401), f"{r.status_code} {r.text}"

    def test_c4_login_ratelimit_kicks_in_at_8(self):
        # Fire 8 bad-password attempts — the 9th SHOULD be 429 (or 401 if the bucket
        # was already partially drained by earlier tests; retry with a couple more to
        # be safe, but if we still can't force 429 we error out).
        got_429 = False
        for i in range(15):
            r = requests.post(
                f"{BASE}/api/auth/login",
                json={"email": PARENT_EMAIL, "password": "definitely-not-right"},
                timeout=15,
            )
            if r.status_code == 429:
                got_429 = True
                break
            assert r.status_code == 401, f"attempt {i}: {r.status_code} {r.text}"
        assert got_429, "login rate limit never triggered after 15 attempts"
