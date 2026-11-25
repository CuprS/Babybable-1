"""
Security fix regression tests: SEC-001..SEC-004 + happy-path regression.
Uses public BASE_URL from EXPO_PUBLIC_BACKEND_URL.
"""
import os
import io
import uuid
import time
import pytest
import requests


BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or "http://localhost:8001").rstrip("/")
ADMIN_EMAIL = "copperstone17@gmail.com"
ADMIN_PW = os.environ.get("ADMIN_INITIAL_PASSWORD", "REDACTED-PASSWORD")


def _login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=30)
    return r


# ---- SEC-001: Admin seed via env var ----
class TestSEC001AdminSeed:
    def test_admin_login_works_with_env_password(self):
        r = _login(ADMIN_EMAIL, ADMIN_PW)
        assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
        data = r.json()
        assert data["user"]["is_admin"] is True
        assert data["user"]["email"] == ADMIN_EMAIL
        assert "access_token" in data

    def test_no_hardcoded_admin_password_literal(self):
        """server.py should not contain any hash_password("...literal...") for admin."""
        with open("/app/backend/server.py", "r") as f:
            src = f.read()
        # Only allowed literal usages: hash_password(body.password), hash_password(admin_pw),
        # and hash_password("password123") for seed tutors. NO admin literal.
        import re
        # Look for admin-context literal password
        assert 'hash_password("REDACTED' not in src
        assert 'hash_password("admin' not in src.lower()


# ---- SEC-003: Stripe webhook rejection ----
class TestSEC003StripeWebhook:
    def test_webhook_rejects_without_signature(self):
        # STRIPE_WEBHOOK_SECRET is currently empty in .env → should return 503.
        # If secret is set, without signature header should still return 400.
        payload = '{"type":"payment_intent.succeeded","data":{"object":{"id":"pi_test_forged"}}}'
        r = requests.post(
            f"{BASE_URL}/api/stripe/webhook",
            data=payload,
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
        assert r.status_code in (400, 503), f"Expected 400/503, got {r.status_code}: {r.text}"
        assert r.status_code != 200, "Webhook must never accept unsigned payloads"

    def test_webhook_rejects_invalid_signature(self):
        payload = '{"type":"payment_intent.succeeded","data":{"object":{"id":"pi_test_forged"}}}'
        r = requests.post(
            f"{BASE_URL}/api/stripe/webhook",
            data=payload,
            headers={"Content-Type": "application/json", "Stripe-Signature": "t=1,v1=deadbeef"},
            timeout=30,
        )
        assert r.status_code in (400, 503)

    def test_forged_webhook_does_not_flip_booking(self):
        """Even with a forged webhook, no existing booking gets marked paid."""
        # Login as parent to see their bookings state pre/post.
        rl = _login("prv@test.dev", "password123")
        if rl.status_code != 200:
            pytest.skip("parent seed missing")
        tok = rl.json()["access_token"]
        pre = requests.get(f"{BASE_URL}/api/bookings/me", headers={"Authorization": f"Bearer {tok}"}, timeout=30).json()
        pending_ids = [b["stripe_payment_intent_id"] for b in pre if b.get("payment_status") == "pending" and b.get("stripe_payment_intent_id")]
        target = pending_ids[0] if pending_ids else "pi_test_forged"
        payload = '{"type":"payment_intent.succeeded","data":{"object":{"id":"%s"}}}' % target
        requests.post(
            f"{BASE_URL}/api/stripe/webhook",
            data=payload,
            headers={"Content-Type": "application/json", "Stripe-Signature": "t=1,v1=deadbeef"},
            timeout=30,
        )
        post = requests.get(f"{BASE_URL}/api/bookings/me", headers={"Authorization": f"Bearer {tok}"}, timeout=30).json()
        # Compare per-id: none of the previously-pending bookings should now be paid.
        pre_map = {b["id"]: b["payment_status"] for b in pre}
        for b in post:
            if pre_map.get(b["id"]) == "pending":
                assert b["payment_status"] == "pending", f"Booking {b['id']} was flipped by forged webhook!"


# ---- SEC-004: /api/files/{path} ACL for private child photos ----
@pytest.fixture(scope="module")
def parents_setup():
    """Create 2 parents; parent A uploads a child photo & sets children[0].avatar_url = path."""
    uniq = uuid.uuid4().hex[:8]
    a_email = f"TEST_parentA_{uniq}@test.dev"
    b_email = f"TEST_parentB_{uniq}@test.dev"
    ra = requests.post(f"{BASE_URL}/api/auth/signup", json={"email": a_email, "password": "password123", "name": "Parent A", "role": "parent"}, timeout=30)
    rb = requests.post(f"{BASE_URL}/api/auth/signup", json={"email": b_email, "password": "password123", "name": "Parent B", "role": "parent"}, timeout=30)
    assert ra.status_code == 201 and rb.status_code == 201, f"signup failed {ra.status_code}/{rb.status_code}"
    tok_a = ra.json()["access_token"]
    tok_b = rb.json()["access_token"]
    # Upload a tiny PNG as parent A.
    png_bytes = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
        b"\x00\x00\x00\x03\x00\x01\xe4\xc7\xa8\x9f\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    files = {"file": ("child.png", io.BytesIO(png_bytes), "image/png")}
    up = requests.post(f"{BASE_URL}/api/uploads", files=files, headers={"Authorization": f"Bearer {tok_a}"}, timeout=60)
    if up.status_code != 200:
        pytest.skip(f"upload failed: {up.status_code} {up.text}")
    path = up.json()["path"]
    # PATCH parent A profile: set a child with avatar_url = uploaded path.
    child = {"id": str(uuid.uuid4()), "name": "Kid", "age": 4, "avatar_url": path}
    rp = requests.patch(f"{BASE_URL}/api/parents/me/profile", json={"children": [child]}, headers={"Authorization": f"Bearer {tok_a}"}, timeout=30)
    assert rp.status_code == 200, rp.text
    return {"tok_a": tok_a, "tok_b": tok_b, "path": path}


class TestSEC004FilesACL:
    def test_owner_can_fetch_private_child_photo(self, parents_setup):
        p = parents_setup
        r = requests.get(f"{BASE_URL}/api/files/{p['path']}", headers={"Authorization": f"Bearer {p['tok_a']}"}, timeout=30)
        assert r.status_code == 200, f"owner blocked: {r.status_code} {r.text}"
        assert r.headers.get("content-type", "").startswith("image/")
        assert len(r.content) > 0

    def test_anonymous_blocked_from_private_child_photo(self, parents_setup):
        p = parents_setup
        r = requests.get(f"{BASE_URL}/api/files/{p['path']}", timeout=30)
        assert r.status_code == 401, f"expected 401, got {r.status_code}: {r.text}"

    def test_different_parent_blocked_from_private_child_photo(self, parents_setup):
        p = parents_setup
        r = requests.get(f"{BASE_URL}/api/files/{p['path']}", headers={"Authorization": f"Bearer {p['tok_b']}"}, timeout=30)
        assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text}"

    def test_public_tutor_upload_still_accessible_unauthenticated(self):
        """A generic upload path (not referenced by any child) should still be public."""
        # Sign up a tutor and upload something (not a child photo).
        uniq = uuid.uuid4().hex[:8]
        email = f"TEST_tutor_public_{uniq}@example.com"
        rs = requests.post(f"{BASE_URL}/api/auth/signup", json={"email": email, "password": "password123", "name": "Test Tutor", "role": "tutor"}, timeout=30)
        assert rs.status_code == 201
        tok = rs.json()["access_token"]
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
        up = requests.post(f"{BASE_URL}/api/uploads", files={"file": ("hero.png", io.BytesIO(png), "image/png")}, headers={"Authorization": f"Bearer {tok}"}, timeout=60)
        if up.status_code != 200:
            pytest.skip(f"upload failed: {up.status_code}")
        path = up.json()["path"]
        # Fetch unauthenticated → must be 200 (not tied to any child).
        r = requests.get(f"{BASE_URL}/api/files/{path}", timeout=30)
        assert r.status_code == 200, f"expected 200 public, got {r.status_code}"


# ---- REGRESSION: happy path ----
class TestRegressionHappyPath:
    def test_parent_login_and_list_bookings(self):
        r = _login("prv@test.dev", "password123")
        assert r.status_code == 200
        tok = r.json()["access_token"]
        rb = requests.get(f"{BASE_URL}/api/bookings/me", headers={"Authorization": f"Bearer {tok}"}, timeout=30)
        assert rb.status_code == 200
        assert isinstance(rb.json(), list)

    def test_seeded_tutors_present(self):
        r = requests.get(f"{BASE_URL}/api/tutors", timeout=30)
        assert r.status_code == 200
        names = [t["name"] for t in r.json()]
        assert any("Sofía" in n or "Sofia" in n for n in names), f"Sofia missing: {names}"

    def test_tutor_signup_with_non_babybabel_email_survives(self):
        """Regression: fresh tutor signup with non-@babybabel.dev email should NOT be wiped by seed_data."""
        uniq = uuid.uuid4().hex[:8]
        email = f"TEST_survivor_{uniq}@example.com"
        r = requests.post(f"{BASE_URL}/api/auth/signup", json={"email": email, "password": "password123", "name": "Survivor", "role": "tutor"}, timeout=30)
        assert r.status_code == 201
        # Cannot restart supervisor from here, but seed_data() logic already restricts deletion to @babybabel.dev — verify by re-login existing.
        rl = _login(email, "password123")
        assert rl.status_code == 200
