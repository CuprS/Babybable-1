import random
"""End-to-end backend tests for Babybabel bug fixes + booking/payment feature."""
import os
import time
import uuid
import subprocess
import pytest
import requests

BASE = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or "https://papyrus-tutors.preview.emergentagent.com").rstrip("/")
API = f"{BASE}/api"

ADMIN_EMAIL = "copperstone17@gmail.com"
ADMIN_PW = "REDACTED-PASSWORD"
PARENT_EMAIL = "prv@test.dev"
PARENT_PW = "password123"
SOFIA = "sofia@babybabel.dev"
MARIE = "marie@babybabel.dev"
SEED_PW = "password123"


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    return r


def _headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# --------- BUG FIX: tutor signup survives restart ---------
class TestTutorSignupPersistence:
    def test_signup_and_survive_restart(self):
        uniq = uuid.uuid4().hex[:8]
        email = f"tutor.new.{uniq}@example.com"
        pw = "password123"
        r = requests.post(f"{API}/auth/signup", json={
            "email": email, "password": pw, "name": f"Test Tutor {uniq}", "role": "tutor",
        }, timeout=30)
        assert r.status_code == 201, r.text
        data = r.json()
        assert data["user"]["email"] == email
        assert data["user"]["role"] == "tutor"

        # Restart backend
        subprocess.run(["sudo", "supervisorctl", "restart", "backend"], check=False, capture_output=True)
        # Poll until backend up
        for _ in range(30):
            time.sleep(1)
            try:
                pr = requests.get(f"{API}/", timeout=5)
                if pr.status_code == 200:
                    break
            except Exception:
                pass
        time.sleep(2)

        r2 = _login(email, pw)
        assert r2.status_code == 200, f"Tutor signup did NOT survive restart. Response: {r2.status_code} {r2.text}"
        assert "access_token" in r2.json()

    def test_seeded_tutors_survive_restart(self):
        # Sofia
        r = _login(SOFIA, SEED_PW)
        assert r.status_code == 200, r.text
        # Marie
        r = _login(MARIE, SEED_PW)
        assert r.status_code == 200, r.text

    def test_admin_survives_restart(self):
        r = _login(ADMIN_EMAIL, ADMIN_PW)
        assert r.status_code == 200, r.text
        assert r.json()["user"]["is_admin"] is True


# --------- FEATURE: GET /api/bookings/{id} ACL ---------
class TestBookingGetACL:
    @pytest.fixture(scope="class")
    def parent_token(self):
        r = _login(PARENT_EMAIL, PARENT_PW)
        if r.status_code != 200:
            # create it
            requests.post(f"{API}/auth/signup", json={
                "email": PARENT_EMAIL, "password": PARENT_PW, "name": "Parent Test", "role": "parent"
            }, timeout=30)
            r = _login(PARENT_EMAIL, PARENT_PW)
        assert r.status_code == 200, r.text
        return r.json()["access_token"]

    @pytest.fixture(scope="class")
    def sofia_tutor(self, parent_token):
        r = requests.get(f"{API}/tutors", headers=_headers(parent_token), timeout=30)
        assert r.status_code == 200
        for t in r.json():
            if t["name"].lower().startswith("sof"):
                return t
        pytest.skip("Sofia tutor not found")

    @pytest.fixture(scope="class")
    def parent_profile_ready(self, parent_token):
        # Ensure Barcelona set as city so distance rule passes for Sofia
        r = requests.patch(f"{API}/parents/me/profile", headers=_headers(parent_token),
                           json={"city": "Barcelona, ES"}, timeout=30)
        assert r.status_code == 200, r.text
        return r.json()

    @pytest.fixture(scope="class")
    def booking(self, parent_token, sofia_tutor, parent_profile_ready):
        r = requests.post(f"{API}/bookings", headers=_headers(parent_token), json={
            "tutor_id": sofia_tutor["id"],
            # random future Monday (Sofia's weekly availability: mon 09:00/10:00) to avoid slot clashes across runs
            "date": (__import__("datetime").date(2031, 1, 6) + __import__("datetime").timedelta(weeks=random.randint(0, 400))).isoformat(),
            "time": random.choice(["09:00", "10:00"]),
            "duration_minutes": 60,
            "language": "Spanish",
            "notes": "TEST_ booking",
            "is_au_pair": False,
            "lessons_count": 1,
        }, timeout=60)
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["payment_status"] == "pending", f"New booking must be pending (not auto-paid). Got: {b['payment_status']}"
        return b

    def test_owner_can_get(self, parent_token, booking):
        r = requests.get(f"{API}/bookings/{booking['id']}", headers=_headers(parent_token), timeout=30)
        assert r.status_code == 200
        assert r.json()["id"] == booking["id"]
        assert r.json()["payment_status"] == "pending"

    def test_other_parent_forbidden(self, booking):
        other_email = f"other.{uuid.uuid4().hex[:8]}@test.dev"
        r0 = requests.post(f"{API}/auth/signup", json={
            "email": other_email, "password": "password123", "name": "Other", "role": "parent"
        }, timeout=30)
        assert r0.status_code == 201, r0.text
        token = r0.json()["access_token"]
        r = requests.get(f"{API}/bookings/{booking['id']}", headers=_headers(token), timeout=30)
        assert r.status_code == 403, f"Expected 403, got {r.status_code}: {r.text}"

    def test_unknown_booking_returns_404(self, parent_token):
        r = requests.get(f"{API}/bookings/{uuid.uuid4()}", headers=_headers(parent_token), timeout=30)
        assert r.status_code == 404

    def test_confirm_mock_flips_to_paid(self, parent_token, booking):
        r = requests.post(f"{API}/bookings/{booking['id']}/confirm-mock", headers=_headers(parent_token), timeout=30)
        assert r.status_code == 200
        assert r.json()["payment_status"] == "paid"
        # Verify via GET
        r2 = requests.get(f"{API}/bookings/{booking['id']}", headers=_headers(parent_token), timeout=30)
        assert r2.status_code == 200
        assert r2.json()["payment_status"] == "paid"
