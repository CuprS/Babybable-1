"""
Session 3 regression suite covering:
  - P3 auth hardening: signup min_length=8, generic duplicate-email, login rate-limit
  - Tutor weekly_availability CRUD + normalization
  - Booking / invitation slot enforcement
  - GET /api/tutors/{id}/booked-slots

Uses public BASE_URL from EXPO_PUBLIC_BACKEND_URL.

NOTE: Rate-limit tests run last (autouse ordering below) and rely on the fact
that they exhaust the login bucket, so any following test that logs in with
the same IP would hit 429. If backend was just restarted the bucket is empty.
"""
import os
import time
import uuid
from datetime import date, timedelta

import pytest
import requests


BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or "https://papyrus-tutors.preview.emergentagent.com").rstrip("/")

PARENT_EMAIL = "parent@test.dev"
PARENT_PW = "password123"
SOFIA_EMAIL = "sofia@babybabel.dev"
TUTOR_PW = "password123"

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


# ---------------- helpers ----------------
def _login(email, pw):
    return requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": pw}, timeout=30)


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def _next_weekday_date(target_wk: str, weeks_ahead: int = 1) -> str:
    """Return YYYY-MM-DD for the next 'mon'/'tue'/... at least `weeks_ahead` weeks ahead."""
    today = date.today()
    tgt_idx = WEEKDAYS.index(target_wk)
    delta = (tgt_idx - today.weekday()) % 7
    if delta == 0:
        delta = 7
    d = today + timedelta(days=delta + 7 * (weeks_ahead - 1))
    return d.isoformat()


@pytest.fixture(scope="session")
def parent_token():
    r = _login(PARENT_EMAIL, PARENT_PW)
    if r.status_code != 200:
        pytest.skip(f"parent login failed: {r.status_code} {r.text}")
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def sofia():
    r = _login(SOFIA_EMAIL, TUTOR_PW)
    if r.status_code != 200:
        pytest.skip(f"sofia login failed: {r.status_code} {r.text}")
    tok = r.json()["access_token"]
    # fetch tutor profile (id) via /tutors listing
    rl = requests.get(f"{BASE_URL}/api/tutors", timeout=30)
    assert rl.status_code == 200
    row = next((t for t in rl.json() if "Sof" in t.get("name", "")), None)
    assert row, "Sofia tutor row not found in /api/tutors"
    return {"token": tok, "tutor_id": row["id"], "user_id_owner_profile": row}


# ========== P3 Auth hardening ==========
class TestSignupPasswordLength:
    def test_password_6_chars_rejected(self):
        email = f"TEST_pw6_{uuid.uuid4().hex[:6]}@test.dev"
        r = requests.post(f"{BASE_URL}/api/auth/signup",
                          json={"email": email, "password": "abcdef", "name": "X", "role": "parent"},
                          timeout=30)
        assert r.status_code == 422, f"expected 422, got {r.status_code}: {r.text}"

    def test_password_7_chars_rejected(self):
        email = f"TEST_pw7_{uuid.uuid4().hex[:6]}@test.dev"
        r = requests.post(f"{BASE_URL}/api/auth/signup",
                          json={"email": email, "password": "abcdefg", "name": "X", "role": "parent"},
                          timeout=30)
        assert r.status_code == 422, f"expected 422, got {r.status_code}: {r.text}"

    def test_password_8_chars_accepted(self):
        email = f"TEST_pw8_{uuid.uuid4().hex[:6]}@test.dev"
        r = requests.post(f"{BASE_URL}/api/auth/signup",
                          json={"email": email, "password": "abcdefgh", "name": "X", "role": "parent"},
                          timeout=30)
        assert r.status_code == 201, f"expected 201, got {r.status_code}: {r.text}"


class TestDuplicateEmailGeneric:
    def test_duplicate_email_returns_400_generic_message(self):
        email = f"TEST_dup_{uuid.uuid4().hex[:6]}@test.dev"
        r1 = requests.post(f"{BASE_URL}/api/auth/signup",
                           json={"email": email, "password": "password123", "name": "X", "role": "parent"},
                           timeout=30)
        assert r1.status_code == 201
        r2 = requests.post(f"{BASE_URL}/api/auth/signup",
                           json={"email": email, "password": "password123", "name": "X", "role": "parent"},
                           timeout=30)
        assert r2.status_code == 400, f"expected 400, got {r2.status_code}: {r2.text}"
        detail = (r2.json().get("detail") or "").lower()
        # Must NOT leak that the email exists.
        assert "already registered" not in detail
        assert "exists" not in detail
        # Should be the generic phrasing.
        assert "couldn't create" in detail or "different email" in detail, f"non-generic message: {detail}"


# ========== Tutor weekly_availability ==========
class TestTutorAvailability:
    def test_patch_normalizes_and_drops_junk(self, sofia):
        payload = {
            "weekly_availability": {
                "mon": ["09:00", "9:00", "10:00", "notatime"],
                "tue": ["07:30", "20:00"],
                "garbage": ["01:00"],
                "MON": ["11:00"],   # wrong case → dropped
            }
        }
        r = requests.patch(f"{BASE_URL}/api/tutors/me/profile",
                           json=payload, headers=_auth(sofia["token"]), timeout=30)
        assert r.status_code == 200, r.text
        wa = r.json().get("weekly_availability") or {}
        assert set(wa.keys()) <= set(WEEKDAYS), f"junk keys leaked: {wa.keys()}"
        assert "garbage" not in wa
        assert "MON" not in wa
        assert wa.get("mon") == ["09:00", "10:00"], f"mon slots wrong: {wa.get('mon')}"
        assert wa.get("tue") == ["07:30", "20:00"], f"tue slots wrong: {wa.get('tue')}"

    def test_get_tutor_exposes_weekly_availability(self, sofia):
        r = requests.get(f"{BASE_URL}/api/tutors/{sofia['tutor_id']}", timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "weekly_availability" in body
        assert isinstance(body["weekly_availability"], dict)
        # After previous test it must contain mon/tue
        assert "mon" in body["weekly_availability"]

    def test_booked_slots_endpoint_returns_list(self, sofia):
        r = requests.get(f"{BASE_URL}/api/tutors/{sofia['tutor_id']}/booked-slots", timeout=30)
        assert r.status_code == 200
        rows = r.json()
        assert isinstance(rows, list)
        for row in rows:
            assert set(row.keys()) >= {"date", "time"}
            # time normalized HH:MM
            assert len(row["time"]) == 5 and row["time"][2] == ":"


# ========== Booking slot enforcement ==========
class TestBookingSlotEnforcement:
    def test_booking_outside_availability_rejected(self, parent_token, sofia):
        # Ensure sofia has mon=09:00,10:00 from earlier test.
        # Pick a Monday, book 15:00 (not in avail) → expect 400.
        mon = _next_weekday_date("mon")
        body = {
            "tutor_id": sofia["tutor_id"],
            "date": mon, "time": "15:00",
            "duration_minutes": 60, "language": "Spanish",
            "notes": "TEST outside-availability", "is_au_pair": False,
            "lessons_count": 1,
        }
        r = requests.post(f"{BASE_URL}/api/bookings", json=body, headers=_auth(parent_token), timeout=30)
        # Might be 400 from distance guard if parent has no lat/lng. Ensure at least it never succeeds.
        assert r.status_code in (400,), f"expected 400 rejection, got {r.status_code}: {r.text}"
        # Prefer message check when it fails on slot rule:
        detail = (r.json().get("detail") or "").lower()
        # Accept either the slot message OR the distance guard IF the parent hasn't set city.
        assert ("isn't available" in detail) or ("city" in detail) or ("miles away" in detail), (
            f"unexpected detail: {detail}"
        )

    def test_booking_in_availability_succeeds_or_needs_city(self, parent_token, sofia):
        """A slot inside sofia's weekly availability should either succeed or fail *only* on
        distance/city checks — not on availability."""
        mon = _next_weekday_date("mon", weeks_ahead=2)
        body = {
            "tutor_id": sofia["tutor_id"],
            "date": mon, "time": "09:00",
            "duration_minutes": 60, "language": "Spanish",
            "notes": "TEST inside-availability", "is_au_pair": False,
            "lessons_count": 1,
        }
        r = requests.post(f"{BASE_URL}/api/bookings", json=body, headers=_auth(parent_token), timeout=30)
        assert r.status_code in (200, 400, 409), r.text
        if r.status_code == 400:
            detail = (r.json().get("detail") or "").lower()
            # Must not be availability
            assert "isn't available" not in detail, f"in-avail slot rejected as unavailable: {detail}"

    def test_double_booking_returns_409(self, parent_token, sofia):
        """Set parent city first, then successfully book, then try to book the same slot → 409."""
        # Set parent lat/lng near Sofia (from Sofia's listing) so distance guard passes.
        rl = requests.get(f"{BASE_URL}/api/tutors/{sofia['tutor_id']}", timeout=30).json()
        lat, lng = rl.get("latitude"), rl.get("longitude")
        loc = rl.get("location") or "Madrid, Spain"
        # If tutor has no coords, skip.
        if lat is None or lng is None:
            pytest.skip("tutor coords missing; distance check would block")
        # Ensure parent profile row exists (GET auto-creates), then set city to co-locate.
        requests.get(f"{BASE_URL}/api/parents/me/profile", headers=_auth(parent_token), timeout=30)
        pp = requests.patch(f"{BASE_URL}/api/parents/me/profile",
                            json={"city": loc},
                            headers=_auth(parent_token), timeout=30)
        assert pp.status_code == 200, pp.text
        # If geocoding didn't set coords (offline geocoder), skip — booking would 400 on city guard.
        p_json = pp.json()
        if p_json.get("latitude") is None:
            pytest.skip("parent geocode unavailable; distance guard would block double-book test")
        mon = _next_weekday_date("mon", weeks_ahead=3)
        body = {
            "tutor_id": sofia["tutor_id"],
            "date": mon, "time": "10:00",
            "duration_minutes": 60, "language": "Spanish",
            "notes": "TEST double-book-1", "is_au_pair": False,
            "lessons_count": 1,
        }
        r1 = requests.post(f"{BASE_URL}/api/bookings", json=body, headers=_auth(parent_token), timeout=30)
        assert r1.status_code == 200, f"first booking should succeed: {r1.status_code} {r1.text}"
        # Now book same tutor/date/time again → 409
        r2 = requests.post(f"{BASE_URL}/api/bookings", json=body, headers=_auth(parent_token), timeout=30)
        assert r2.status_code == 409, f"expected 409 double-book, got {r2.status_code}: {r2.text}"
        assert "just booked" in (r2.json().get("detail") or "").lower()


# ========== Invitation slot enforcement ==========
class TestInvitationSlotEnforcement:
    def test_invitation_outside_availability_rejected(self, parent_token, sofia):
        # Parent info to invite
        me = requests.get(f"{BASE_URL}/api/auth/me", headers=_auth(parent_token), timeout=30).json()
        wed = _next_weekday_date("wed")
        body = {
            "to_user_id": me["id"],
            "price_cents": 3000,
            "date": wed, "time": "22:00",  # tutor has no wed availability set
            "duration_minutes": 60,
            "language": "Spanish",
            "note": "TEST invitation outside avail",
        }
        r = requests.post(f"{BASE_URL}/api/messages/invitation",
                          json=body, headers=_auth(sofia["token"]), timeout=30)
        assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"
        assert "weekly availability" in (r.json().get("detail") or "").lower()

    def test_invitation_inside_availability_accepted(self, parent_token, sofia):
        me = requests.get(f"{BASE_URL}/api/auth/me", headers=_auth(parent_token), timeout=30).json()
        mon = _next_weekday_date("mon", weeks_ahead=4)
        body = {
            "to_user_id": me["id"],
            "price_cents": 3000,
            "date": mon, "time": "09:00",  # inside sofia's mon avail
            "duration_minutes": 60,
            "language": "Spanish",
            "note": "TEST invitation inside avail",
        }
        r = requests.post(f"{BASE_URL}/api/messages/invitation",
                          json=body, headers=_auth(sofia["token"]), timeout=30)
        assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text}"
        assert r.json().get("kind") == "invitation"


# ========== Login rate-limit (LAST — will exhaust bucket) ==========
class TestLoginRateLimit:
    """MUST run last. Exhausts the login bucket for this IP."""
    def test_login_9th_attempt_returns_429_with_retry_after(self):
        # Use a fresh non-existent email so we never lock a real account (401s are fine).
        email = f"TEST_ratelimit_{uuid.uuid4().hex[:6]}@test.dev"
        codes = []
        for _ in range(8):
            r = requests.post(f"{BASE_URL}/api/auth/login",
                              json={"email": email, "password": "wrongpass"}, timeout=30)
            codes.append(r.status_code)
        # 9th attempt should be 429 with Retry-After header
        r = requests.post(f"{BASE_URL}/api/auth/login",
                          json={"email": email, "password": "wrongpass"}, timeout=30)
        codes.append(r.status_code)
        assert r.status_code == 429, f"expected 429 on 9th attempt, got {r.status_code}. Sequence: {codes}"
        assert r.headers.get("Retry-After"), "missing Retry-After header on 429"
        # Retry-After should be a positive int
        assert int(r.headers["Retry-After"]) >= 1
