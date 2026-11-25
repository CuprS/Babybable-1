"""
Session-9 security fix verifications.

Covers:
  SEC-001  Mock payment env-gated (ENABLE_MOCK_CONFIRM)
  SEC-002  Accreditation docs require auth
  SEC-003  Cache-Control: private, no-store for private/restricted files
  P3       XFF rightmost IP for rate limiter
  P3       role=admin rejected on signup
  P3       Search ReDoS mitigated (re.escape + 80-char truncate)
  P3       DELETE /api/auth/me purges ancillary collections

Uses public BASE_URL from EXPO_PUBLIC_BACKEND_URL and the seeded admin/parent/
tutor accounts created by the seed (see README → Tests).
"""
import io
import os
import re
import time
import uuid
import asyncio
import importlib
import pytest
import requests


BASE_URL = (
    os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or "http://localhost:8001"
).rstrip("/")
# Direct origin base URL (bypasses Cloudflare/ingress which rewrites Cache-Control
# on all responses to "no-store, no-cache, must-revalidate"). We use this only for
# Cache-Control header assertions; the origin still enforces the ACL identically.
ORIGIN_URL = "http://localhost:8001"

ADMIN_EMAIL = "copperstone17@gmail.com"
ADMIN_PW = os.environ.get("ADMIN_INITIAL_PASSWORD", "REDACTED-PASSWORD")
PARENT_EMAIL = "parent@test.dev"
PARENT_PW = "password123"
TUTOR_EMAIL = "sofia@babybabel.dev"
TUTOR_PW = "password123"


# ---------- small helpers ----------

def _login(email, password):
    return requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": email, "password": password},
        timeout=30,
    )


def _token_for(email, password):
    r = _login(email, password)
    if r.status_code != 200:
        pytest.skip(f"login failed for {email}: {r.status_code} {r.text}")
    return r.json()["access_token"]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}"}


PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
    b"\x00\x00\x00\x03\x00\x01\xe4\xc7\xa8\x9f\x00\x00\x00\x00IEND\xaeB`\x82"
)


# =====================================================================
# P3  role=admin rejected on signup
# =====================================================================
class TestSignupRoleAdmin:
    def test_signup_role_admin_rejected(self):
        uniq = uuid.uuid4().hex[:8]
        email = f"TEST_admin_signup_{uniq}@test.dev"
        r = requests.post(
            f"{BASE_URL}/api/auth/signup",
            json={"email": email, "password": "password123", "name": "Nope", "role": "admin"},
            timeout=30,
        )
        assert r.status_code == 400, f"expected 400, got {r.status_code} {r.text}"
        # message content check — server returns "Invalid role"
        body = r.json()
        assert "Invalid role" in str(body), f"expected 'Invalid role' in body, got {body}"

    def test_signup_role_parent_still_works(self):
        uniq = uuid.uuid4().hex[:8]
        email = f"TEST_parent_ok_{uniq}@test.dev"
        r = requests.post(
            f"{BASE_URL}/api/auth/signup",
            json={"email": email, "password": "password123", "name": "OK Parent", "role": "parent"},
            timeout=30,
        )
        assert r.status_code == 201, f"expected 201, got {r.status_code} {r.text}"
        data = r.json()
        assert data["user"]["role"] == "parent"
        assert data["user"]["is_admin"] is False
        # cleanup
        tok = data["access_token"]
        requests.delete(f"{BASE_URL}/api/auth/me", headers=_hdr(tok), timeout=30)

    def test_signup_role_garbage_rejected(self):
        uniq = uuid.uuid4().hex[:8]
        email = f"TEST_garbage_{uniq}@test.dev"
        r = requests.post(
            f"{BASE_URL}/api/auth/signup",
            json={"email": email, "password": "password123", "name": "Nope", "role": "superuser"},
            timeout=30,
        )
        # Pydantic may reject via 422 OR server via 400. Both are acceptable ("not accepted").
        assert r.status_code in (400, 422), f"got {r.status_code}"


# =====================================================================
# P3  Search ReDoS mitigation
# =====================================================================
class TestSearchReDoS:
    def test_pathological_regex_returns_fast_and_empty(self):
        # (a+)+$ is the classic catastrophic-backtracking pattern.
        t0 = time.time()
        r = requests.get(f"{BASE_URL}/api/tutors", params={"q": "(a+)+$"}, timeout=10)
        elapsed = time.time() - t0
        assert r.status_code == 200, f"got {r.status_code} {r.text}"
        assert isinstance(r.json(), list)
        # No tutor is literally named "(a+)+$".
        assert r.json() == [], f"expected empty, got {r.json()}"
        # Fast — the request round-trip over the internet can be several hundred ms,
        # so we assert <5s, which is many orders of magnitude below a live ReDoS.
        assert elapsed < 5.0, f"search took {elapsed:.2f}s — ReDoS likely still exploitable"

    def test_over_long_query_truncates_and_returns_200(self):
        long_q = "a" * 500
        r = requests.get(f"{BASE_URL}/api/tutors", params={"q": long_q}, timeout=10)
        assert r.status_code == 200, r.text
        assert isinstance(r.json(), list)

    def test_normal_search_still_returns_sofia(self):
        # Use accent-free ASCII substring that IS a literal match ("Sof" appears in
        # "Sofía"). Note: re.escape lowercases don't fold í→i, but that predates the
        # ReDoS fix — behaviour parity, not a regression.
        r = requests.get(f"{BASE_URL}/api/tutors", params={"q": "Sof"}, timeout=10)
        assert r.status_code == 200
        names = [t["name"] for t in r.json()]
        assert any("Sofía" in n or "Sofia" in n for n in names), f"Sofia missing: {names}"

    def test_search_special_chars_treated_literally(self):
        # A regex "$" would anchor end-of-string; literal "$" should match nothing.
        r = requests.get(f"{BASE_URL}/api/tutors", params={"q": "$$$"}, timeout=10)
        assert r.status_code == 200
        assert r.json() == [], "'$$$' should be treated as literal after re.escape"


# =====================================================================
# SEC-001  Mock payment env-gated
# NOTE: We can't set env vars on the live uvicorn process from a
# request-level test. `ENABLE_MOCK_CONFIRM` is "true" in .env (dev-default),
# so we assert the DEV path works and use monkeypatch of `os.environ` on
# an in-process import of server.py to prove the "false" branch returns 410.
# =====================================================================
class TestMockConfirmEnvGate:
    def test_default_dev_mock_confirm_still_flips_status(self):
        parent_tok = _token_for(PARENT_EMAIL, PARENT_PW)
        # Find a seeded tutor to book against
        tr = requests.get(f"{BASE_URL}/api/tutors", timeout=30).json()
        tutor = next((t for t in tr if "Sof" in t["name"]), tr[0] if tr else None)
        assert tutor, "no tutors seeded"
        # Try slots derived from the tutor's weekly_availability against a matching future weekday.
        wa = tutor.get("weekly_availability") or {}
        weekday_names = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
        import datetime as _dt
        today = _dt.date.today()
        candidates = []
        # Prefer availability-derived slots
        for wd_key, slots in wa.items():
            wd_num = weekday_names.get(wd_key)
            if wd_num is None or not slots:
                continue
            # Next occurrence of this weekday >= today + 14 days
            days_ahead = (wd_num - today.weekday()) % 7
            date = today + _dt.timedelta(days=(days_ahead + 21))
            for slot in slots:
                candidates.append((date.isoformat(), slot))
        # Fallback: try common slots on next-week days
        for i in [7, 14, 21, 28]:
            candidates.append(((today + _dt.timedelta(days=i)).isoformat(), "10:00"))
        bid = None
        for date_str, time_str in candidates:
            rb = requests.post(
                f"{BASE_URL}/api/bookings",
                json={
                    "tutor_id": tutor["id"],
                    "date": date_str,
                    "time": time_str,
                    "duration_minutes": 60,
                    "language": tutor["languages"][0] if tutor["languages"] else "English",
                    "mode": "remote",
                },
                headers=_hdr(parent_tok),
                timeout=30,
            )
            if rb.status_code in (200, 201):
                bid = rb.json()["id"]
                break
        if not bid:
            pytest.skip("could not create a booking on any candidate slot (availability constraints)")
        cm = requests.post(
            f"{BASE_URL}/api/bookings/{bid}/confirm-mock",
            headers=_hdr(parent_tok),
            timeout=30,
        )
        # env is "true" in dev → must succeed
        assert cm.status_code in (200, 201), f"expected 200/201 with ENABLE_MOCK_CONFIRM=true, got {cm.status_code} {cm.text}"
        assert cm.json()["payment_status"] == "paid"

    def test_env_gate_false_returns_410_and_true_allows(self):
        """Full-cycle: flip ENABLE_MOCK_CONFIRM=false in .env, restart backend, verify 410,
        then restore to true and verify a real confirm succeeds. The env gate runs
        BEFORE the DB booking lookup, so we can hit any booking id in phase A."""
        from _support import ENV_FILE, restart_backend
        if not os.environ.get("BACKEND_RESTART_CMD"):
            pytest.skip("needs BACKEND_RESTART_CMD (the same check runs in tests_inprocess)")
        env_path = ENV_FILE
        with open(env_path) as f:
            original = f.read()
        if not re.search(r'^ENABLE_MOCK_CONFIRM="?true"?', original, re.M):
            pytest.skip("backend/.env must contain ENABLE_MOCK_CONFIRM=true for this test")

        # ---- Phase A: force false, expect 410 ----
        modified = re.sub(r'^ENABLE_MOCK_CONFIRM=.*$', 'ENABLE_MOCK_CONFIRM=false', original, flags=re.M)
        with open(env_path, "w") as f:
            f.write(modified)
        restart_backend()

        try:
            parent_tok = _token_for(PARENT_EMAIL, PARENT_PW)
            # Env gate is checked BEFORE db.bookings.find_one, so any id works.
            cm = requests.post(
                f"{BASE_URL}/api/bookings/does-not-exist-{uuid.uuid4().hex}/confirm-mock",
                headers=_hdr(parent_tok),
                timeout=30,
            )
            assert cm.status_code == 410, f"expected 410 with ENABLE_MOCK_CONFIRM=false, got {cm.status_code} {cm.text}"
            assert "disabled" in cm.text.lower()

            # AND: even a genuine existing booking must not flip to paid while gate is closed.
            # Look up an existing pending booking for the parent, if any.
            mine = requests.get(f"{BASE_URL}/api/bookings/me", headers=_hdr(parent_tok), timeout=30).json()
            pending = next((b for b in mine if b.get("payment_status") == "pending"), None)
            if pending:
                cm2 = requests.post(
                    f"{BASE_URL}/api/bookings/{pending['id']}/confirm-mock",
                    headers=_hdr(parent_tok),
                    timeout=30,
                )
                assert cm2.status_code == 410
                # Re-read → still not paid
                gb = requests.get(f"{BASE_URL}/api/bookings/{pending['id']}", headers=_hdr(parent_tok), timeout=30)
                assert gb.status_code == 200 and gb.json()["payment_status"] != "paid"
        finally:
            # ---- Restore for downstream tests + prod default ----
            with open(env_path, "w") as f:
                f.write(original)
            restart_backend()

        # ---- Phase B: restored to true — verify a NEW booking can be flipped paid ----
        parent_tok = _token_for(PARENT_EMAIL, PARENT_PW)
        tr = requests.get(f"{BASE_URL}/api/tutors", timeout=30).json()
        tutor = next((t for t in tr if "Sof" in t["name"]), tr[0] if tr else None)
        assert tutor, "no tutors seeded"
        # Derive slots from weekly_availability
        wa = tutor.get("weekly_availability") or {}
        weekday_names = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
        import datetime as _dt
        today = _dt.date.today()
        candidates = []
        for wd_key, slots in wa.items():
            wd_num = weekday_names.get(wd_key)
            if wd_num is None or not slots:
                continue
            days_ahead = (wd_num - today.weekday()) % 7
            date = today + _dt.timedelta(days=(days_ahead + 28))
            for slot in slots:
                candidates.append((date.isoformat(), slot))
        for i in [7, 14, 21, 35]:
            candidates.append(((today + _dt.timedelta(days=i)).isoformat(), "10:00"))
        bid = None
        for date_str, time_str in candidates:
            rb = requests.post(
                f"{BASE_URL}/api/bookings",
                json={
                    "tutor_id": tutor["id"],
                    "date": date_str,
                    "time": time_str,
                    "duration_minutes": 60,
                    "language": tutor["languages"][0] if tutor["languages"] else "English",
                    "mode": "remote",
                },
                headers=_hdr(parent_tok),
                timeout=30,
            )
            if rb.status_code in (200, 201):
                bid = rb.json()["id"]
                break
        if not bid:
            pytest.skip("could not create a booking on any slot for phase B — availability constraints")
        cm = requests.post(
            f"{BASE_URL}/api/bookings/{bid}/confirm-mock",
            headers=_hdr(parent_tok),
            timeout=30,
        )
        assert cm.status_code in (200, 201), f"expected 200 with restored ENABLE_MOCK_CONFIRM=true, got {cm.status_code} {cm.text}"
        assert cm.json()["payment_status"] == "paid"


# =====================================================================
# SEC-002 + SEC-003  Accreditation files require auth + Cache-Control
# =====================================================================
@pytest.fixture(scope="module")
def accreditation_setup():
    """
    Fresh tutor uploads an image and PATCHes it into `accreditation_photo_url`.
    Also creates a plain public upload (not tied to anything) for the public-cache test.
    Returns tokens + paths.
    """
    uniq = uuid.uuid4().hex[:8]
    tutor_email = f"TEST_acc_tutor_{uniq}@test.dev"
    parent_email = f"TEST_acc_parent_{uniq}@test.dev"

    # signup fresh tutor
    rt = requests.post(
        f"{BASE_URL}/api/auth/signup",
        json={"email": tutor_email, "password": "password123", "name": "Acc Tutor", "role": "tutor"},
        timeout=30,
    )
    assert rt.status_code == 201, f"tutor signup failed: {rt.status_code} {rt.text}"
    tok_tutor = rt.json()["access_token"]

    # signup fresh parent
    rp = requests.post(
        f"{BASE_URL}/api/auth/signup",
        json={"email": parent_email, "password": "password123", "name": "Acc Parent", "role": "parent"},
        timeout=30,
    )
    assert rp.status_code == 201, f"parent signup failed: {rp.status_code} {rp.text}"
    tok_parent = rp.json()["access_token"]

    # upload accreditation image as tutor
    up = requests.post(
        f"{BASE_URL}/api/uploads",
        files={"file": ("acc.png", io.BytesIO(PNG_BYTES), "image/png")},
        headers=_hdr(tok_tutor),
        timeout=60,
    )
    if up.status_code != 200:
        pytest.skip(f"upload failed: {up.status_code} {up.text}")
    acc_path = up.json()["path"]

    # PATCH profile with accreditation_photo_url
    pr = requests.patch(
        f"{BASE_URL}/api/tutors/me/profile",
        json={"accreditation_photo_url": acc_path},
        headers=_hdr(tok_tutor),
        timeout=30,
    )
    assert pr.status_code == 200, f"profile patch failed: {pr.status_code} {pr.text}"

    # separate PUBLIC upload (not referenced by any accreditation or child)
    up2 = requests.post(
        f"{BASE_URL}/api/uploads",
        files={"file": ("public.png", io.BytesIO(PNG_BYTES), "image/png")},
        headers=_hdr(tok_tutor),
        timeout=60,
    )
    assert up2.status_code == 200, up2.text
    public_path = up2.json()["path"]

    yield {
        "tok_tutor": tok_tutor,
        "tok_parent": tok_parent,
        "acc_path": acc_path,
        "public_path": public_path,
        "tutor_email": tutor_email,
        "parent_email": parent_email,
    }

    # cleanup — delete accounts (also purges uploads on tutor account per session-9 fix)
    try:
        requests.delete(f"{BASE_URL}/api/auth/me", headers=_hdr(tok_tutor), timeout=30)
    except Exception:
        pass
    try:
        requests.delete(f"{BASE_URL}/api/auth/me", headers=_hdr(tok_parent), timeout=30)
    except Exception:
        pass


class TestAccreditationFilesACL:
    def test_anonymous_blocked_from_accreditation_file(self, accreditation_setup):
        p = accreditation_setup
        r = requests.get(f"{BASE_URL}/api/files/{p['acc_path']}", timeout=30)
        assert r.status_code == 401, f"expected 401, got {r.status_code} {r.text}"

    def test_parent_can_view_accreditation_file(self, accreditation_setup):
        p = accreditation_setup
        # Cache-Control assertion must be against origin — CDN rewrites it on egress.
        r = requests.get(
            f"{ORIGIN_URL}/api/files/{p['acc_path']}",
            headers=_hdr(p["tok_parent"]),
            timeout=30,
        )
        assert r.status_code == 200, f"parent blocked: {r.status_code} {r.text}"
        assert r.headers.get("Cache-Control", "").strip().lower() == "private, no-store", \
            f"expected 'private, no-store', got {r.headers.get('Cache-Control')!r}"
        assert len(r.content) > 0

    def test_tutor_owner_can_view_accreditation_file(self, accreditation_setup):
        p = accreditation_setup
        r = requests.get(
            f"{ORIGIN_URL}/api/files/{p['acc_path']}",
            headers=_hdr(p["tok_tutor"]),
            timeout=30,
        )
        assert r.status_code == 200
        assert r.headers.get("Cache-Control", "").strip().lower() == "private, no-store"

    def test_admin_can_view_accreditation_file(self, accreditation_setup):
        p = accreditation_setup
        admin_tok = _token_for(ADMIN_EMAIL, ADMIN_PW)
        r = requests.get(
            f"{ORIGIN_URL}/api/files/{p['acc_path']}",
            headers=_hdr(admin_tok),
            timeout=30,
        )
        assert r.status_code == 200
        assert r.headers.get("Cache-Control", "").strip().lower() == "private, no-store"

    def test_public_upload_still_anonymous_with_public_cache(self, accreditation_setup):
        p = accreditation_setup
        r = requests.get(f"{ORIGIN_URL}/api/files/{p['public_path']}", timeout=30)
        assert r.status_code == 200, f"public upload should be anon-accessible; got {r.status_code} {r.text}"
        cc = r.headers.get("Cache-Control", "").strip().lower()
        assert cc == "public, max-age=86400", f"expected 'public, max-age=86400', got {cc!r}"


# =====================================================================
# SEC-003 (child avatar branch)  private, no-store on private child photo
# =====================================================================
@pytest.fixture(scope="module")
def child_avatar_setup():
    uniq = uuid.uuid4().hex[:8]
    parent_email = f"TEST_child_parent_{uniq}@test.dev"
    rp = requests.post(
        f"{BASE_URL}/api/auth/signup",
        json={"email": parent_email, "password": "password123", "name": "Child Parent", "role": "parent"},
        timeout=30,
    )
    assert rp.status_code == 201, rp.text
    tok = rp.json()["access_token"]
    up = requests.post(
        f"{BASE_URL}/api/uploads",
        files={"file": ("kid.png", io.BytesIO(PNG_BYTES), "image/png")},
        headers=_hdr(tok),
        timeout=60,
    )
    assert up.status_code == 200, up.text
    path = up.json()["path"]
    child = {"id": str(uuid.uuid4()), "name": "Kid", "age": 4, "avatar_url": path}
    pr = requests.patch(
        f"{BASE_URL}/api/parents/me/profile",
        json={"children": [child]},
        headers=_hdr(tok),
        timeout=30,
    )
    assert pr.status_code == 200, pr.text
    yield {"tok": tok, "path": path, "parent_email": parent_email}
    try:
        requests.delete(f"{BASE_URL}/api/auth/me", headers=_hdr(tok), timeout=30)
    except Exception:
        pass


class TestChildAvatarPrivateCache:
    def test_owner_gets_private_no_store(self, child_avatar_setup):
        c = child_avatar_setup
        # Origin check — CDN rewrites Cache-Control on egress.
        r = requests.get(
            f"{ORIGIN_URL}/api/files/{c['path']}",
            headers=_hdr(c["tok"]),
            timeout=30,
        )
        assert r.status_code == 200, r.text
        assert r.headers.get("Cache-Control", "").strip().lower() == "private, no-store", \
            r.headers.get("Cache-Control")


# =====================================================================
# P3  XFF rightmost IP for rate-limit key
# =====================================================================
class TestXFFRightmostIP:
    def test_rate_limit_keys_on_rightmost_xff(self):
        """
        With login limit = 8/300s: send 9 requests with the SAME rightmost XFF
        but a rotating leftmost (attacker-controlled) value. The rightmost is
        what the app trusts, so the 9th MUST hit 429.
        """
        # Restart backend to clear the in-memory rate buckets so this test is
        # order-independent.
        from _support import restart_backend
        restart_backend()

        rightmost = "203.0.113.77"  # documentation-range, treated as trusted client IP
        codes = []
        for i in range(9):
            leftmost = f"10.0.0.{i}"  # attacker rotates this
            r = requests.post(
                f"{BASE_URL}/api/auth/login",
                json={"email": "TEST_no_such_user@test.dev", "password": "wrong"},
                headers={"X-Forwarded-For": f"{leftmost}, {rightmost}"},
                timeout=30,
            )
            codes.append(r.status_code)
        assert 429 in codes, (
            f"expected 429 among 9 requests (rightmost-IP bucketing), got {codes}. "
            "If none returned 429, the limiter may still be keying off the leftmost XFF."
        )
        # And the FIRST 8 should all be 401 (invalid creds) since limit is 8/300s.
        assert codes[:8].count(401) >= 6, f"too few 401s in first 8: {codes}"

    def test_no_xff_still_uses_client_host(self):
        """Sanity: with no XFF, limiter falls back to request.client.host so the
        API still works for a normal user coming from the ingress fallback."""
        # Restart to clear buckets so this test doesn't hit the rate limit
        from _support import restart_backend
        restart_backend()
        r = requests.get(f"{BASE_URL}/api/tutors", timeout=30)
        assert r.status_code == 200


# =====================================================================
# P3  DELETE /api/auth/me purges ancillary collections
# =====================================================================
class TestDeleteAccountPurge:
    def test_delete_account_purges_all_pii_collections(self):
        """
        Create a fresh tutor. Generate: a W-9 form, a favorite, a booking (→ event/notification),
        and an upload. Delete the account and query MongoDB directly to verify every
        ancillary collection is empty for that uid.
        """
        # Fresh tutor + a parent that will book them (to generate notifications/events)
        uniq = uuid.uuid4().hex[:8]
        tutor_email = f"sec-fixup-tutor-{uniq}@test.dev"
        parent_email = f"sec-fixup-parent-{uniq}@test.dev"
        rt = requests.post(
            f"{BASE_URL}/api/auth/signup",
            json={"email": tutor_email, "password": "password123", "name": "Fixup Tutor", "role": "tutor"},
            timeout=30,
        )
        assert rt.status_code == 201, rt.text
        tok_tutor = rt.json()["access_token"]
        uid_tutor = rt.json()["user"]["id"]

        rp = requests.post(
            f"{BASE_URL}/api/auth/signup",
            json={"email": parent_email, "password": "password123", "name": "Fixup Parent", "role": "parent"},
            timeout=30,
        )
        assert rp.status_code == 201, rp.text
        tok_parent = rp.json()["access_token"]

        # 1) Upload — writes to db.uploads with owner_id=uid_tutor
        up = requests.post(
            f"{BASE_URL}/api/uploads",
            files={"file": ("x.png", io.BytesIO(PNG_BYTES), "image/png")},
            headers=_hdr(tok_tutor),
            timeout=60,
        )
        assert up.status_code == 200, up.text

        # 2) W-9 submission — writes to db.w9_forms with tutor_user_id=uid_tutor
        w9 = requests.post(
            f"{BASE_URL}/api/w9",
            json={
                "legal_name": "Fixup Tutor",
                "business_name": "",
                "tax_classification": "individual",
                "address": "1 Test Way",
                "city": "Testville",
                "state": "CA",
                "zip_code": "94103",
                "country": "US",
                "tin_type": "ssn",
                "tin": "123-45-6789",
                "signature_name": "Fixup Tutor",
                "is_us_person": True,
                "exempt_from_backup": False,
            },
            headers=_hdr(tok_tutor),
            timeout=30,
        )
        # W-9 might return 200 or 201; either fine. If schema drift, skip the assertion but proceed.
        if w9.status_code not in (200, 201):
            pytest.skip(f"W-9 submit failed unexpectedly: {w9.status_code} {w9.text}")

        # 3) Favorite — parent favorites the tutor → db.favorites for parent AND creates a notification for tutor
        tutors = requests.get(f"{BASE_URL}/api/tutors", timeout=30).json()
        this_tutor = next((t for t in tutors if t["user_id"] == uid_tutor), None)
        # Also have tutor favorite something so db.favorites has a row for uid_tutor
        # (favorites are keyed on user_id — a tutor can also POST /favorites/{tutor_id})
        other = next((t for t in tutors if t["user_id"] != uid_tutor), None)
        if other:
            requests.post(f"{BASE_URL}/api/favorites/{other['id']}", headers=_hdr(tok_tutor), timeout=30)

        # 4) Booking parent→this_tutor → generates events + notifications for both sides
        if this_tutor:
            bk = requests.post(
                f"{BASE_URL}/api/bookings",
                json={
                    "tutor_id": this_tutor["id"],
                    "date": "2099-01-15",
                    "time": "10:00",
                    "duration_minutes": 60,
                    "language": this_tutor["languages"][0] if this_tutor["languages"] else "English",
                    "mode": "remote",
                },
                headers=_hdr(tok_parent),
                timeout=30,
            )
            # confirm-mock to fire notifications for tutor
            if bk.status_code in (200, 201):
                requests.post(
                    f"{BASE_URL}/api/bookings/{bk.json()['id']}/confirm-mock",
                    headers=_hdr(tok_parent),
                    timeout=30,
                )

        # PRE-DELETE DB SNAPSHOT
        pre = self._db_snapshot(uid_tutor)
        # We should have populated at least uploads + users, and ideally w9/notifications/favorites.
        assert pre["users"] is not None, "user row missing before delete"
        assert pre["uploads"] is not None, "no upload row for tutor before delete"

        # DELETE
        rd = requests.delete(f"{BASE_URL}/api/auth/me", headers=_hdr(tok_tutor), timeout=30)
        assert rd.status_code == 200, f"delete failed: {rd.status_code} {rd.text}"
        assert rd.json().get("deleted") is True

        # POST-DELETE DB CHECKS
        post = self._db_snapshot(uid_tutor)
        assert post["users"] is None, "users row still exists"
        # W-9s are retained (IRS: 4 years), flagged for purge, TIN still encrypted.
        if post["w9_forms"] is not None:
            assert post["w9_forms"].get("account_deleted_at"), "retained W-9 not flagged as deleted"
            assert post["w9_forms"].get("retain_until"), "retained W-9 has no purge date"
            assert "123456789" not in str(post["w9_forms"]), "TIN stored in plain text"
        assert post["notifications"] is None, "notifications row still exists"
        assert post["events"] is None, "events row still exists"
        assert post["favorites"] is None, "favorites row still exists"
        assert post["uploads"] is None, "uploads row still exists"

        # cleanup parent
        try:
            requests.delete(f"{BASE_URL}/api/auth/me", headers=_hdr(tok_parent), timeout=30)
        except Exception:
            pass

    @staticmethod
    def _db_snapshot(uid: str):
        """Query MongoDB directly for any row referencing uid across the purge scope."""
        from pymongo import MongoClient
        client = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
        db = client[os.environ.get("DB_NAME", "test_database")]
        return {
            "users":         db.users.find_one({"id": uid}, {"_id": 0}),
            "w9_forms":      db.w9_forms.find_one({"tutor_user_id": uid}, {"_id": 0}),
            "notifications": db.notifications.find_one({"user_id": uid}, {"_id": 0}),
            "events":        db.events.find_one({"user_id": uid}, {"_id": 0}),
            "favorites":     db.favorites.find_one({"user_id": uid}, {"_id": 0}),
            "uploads":       db.uploads.find_one({"owner_id": uid}, {"_id": 0}),
        }


# =====================================================================
# Static source assertions — defense-in-depth against code drift
# =====================================================================
class TestSourceGuards:
    def test_client_ip_uses_rightmost_xff(self):
        from _support import backend_source
        src = backend_source()
        # Match the _client_ip function body
        m = re.search(r"def _client_ip\(request: Request\).*?return[^\n]*\n\n", src, re.DOTALL)
        assert m, "could not locate _client_ip"
        body = m.group(0)
        # The trusted value MUST be parts[-1] (rightmost). parts[0] would be the bug.
        assert "parts[-1]" in body, "expected _client_ip to pick rightmost XFF (parts[-1])"
        assert "parts[0]" not in body, "_client_ip still picks leftmost XFF"

    def test_confirm_mock_env_check_present(self):
        from _support import backend_source
        src = backend_source()
        assert 'ENABLE_MOCK_CONFIRM' in src
        assert re.search(r"os\.getenv\(\s*[\"']ENABLE_MOCK_CONFIRM", src), \
            "ENABLE_MOCK_CONFIRM not read via os.getenv"

    def test_search_uses_re_escape_and_truncation(self):
        from _support import backend_source
        src = backend_source()
        assert re.search(r"re\.escape\(.*?\)\[:\s*80\s*\]", src), \
            "search query is not re.escape'd + truncated"

    def test_delete_account_purges_all_collections(self):
        from _support import backend_source
        src = backend_source()
        # Find delete_account function body
        m = re.search(r"async def delete_account\(.*?(?=\n\n\n|\n@|\Z)", src, re.DOTALL)
        assert m, "could not locate delete_account"
        body = m.group(0)
        for coll in ("notifications", "events", "favorites", "uploads", "push_tokens"):
            assert f"db.{coll}.delete_many" in body, f"delete_account does not purge db.{coll}"
        # W-9s are retained (IRS) and flagged for a later purge rather than deleted.
        assert "db.w9_forms.update_many" in body and "retain_until" in body
