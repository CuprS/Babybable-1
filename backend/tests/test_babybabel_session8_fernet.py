"""
Session-8 backend feature tests for Babybabel — Fernet + MultiFernet TIN encryption.

Covers:
1) W9_ENCRYPTION_KEYS picked up from .env (admin encryption-status endpoint).
2) Fernet on the write path — DB token is gAAAAA…, no raw digits leak, response
   never contains tin_encrypted.
3) Round-trip decryption via server.decrypt_tin.
4) Encryption-status counts (records_total/records_on_primary_key), parent → 403.
5) Legacy base64 fallback in decrypt_tin + is_legacy_tin_token.
6) Startup migration idempotency (Fernet token untouched; legacy → gAAAAA…).
7) Unique index on tutor_user_id.
8) Regression: rerun session-7 externally (documented in report).
"""
import os
import sys
import uuid
import base64
import asyncio
import pytest
import requests
import pymongo
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

# Make backend/server.py importable for direct helper testing
BACKEND_DIR = str(Path(__file__).resolve().parents[1])
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

# One persistent event loop for direct server.* async calls so motor's client
# doesn't get orphaned between asyncio.run() calls (each of which closes the loop).
_LOOP = asyncio.new_event_loop()


def _run_on_persistent_loop(coro_factory):
    """Rebind server.client/db to a motor client bound to _LOOP, then run coro."""
    _fresh_client = AsyncIOMotorClient(os.environ["MONGO_URL"], io_loop=_LOOP)
    server.client = _fresh_client
    server.db = _fresh_client[os.environ["DB_NAME"]]
    return _LOOP.run_until_complete(coro_factory())


BASE = os.environ.get(
    "EXPO_PUBLIC_BACKEND_URL", "https://papyrus-tutors.preview.emergentagent.com"
).rstrip("/")

_mongo = pymongo.MongoClient(os.environ["MONGO_URL"])
_db = _mongo[os.environ["DB_NAME"]]

SOFIA_EMAIL = "sofia@babybabel.dev"
SOFIA_PW = "password123"
PARENT_EMAIL = "parent@test.dev"
PARENT_PW = "password123"
ADMIN_EMAIL = "copperstone17@gmail.com"
ADMIN_PW = "REDACTED-PASSWORD"


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


def _valid_payload(**overrides):
    p = {
        "legal_name": "Sofia Garcia",
        "business_name": "",
        "tax_classification": "individual",
        "llc_tax_class": "",
        "other_classification": "",
        "address": "1 Rambla",
        "city": "Barcelona",
        "state": "CA",
        "zip_code": "08001",
        "country": "US",
        "tin_type": "ssn",
        "tin": "123-45-6789",
        "signature_name": "Sofia Garcia",
        "is_us_person": True,
        "exempt_from_backup": False,
    }
    p.update(overrides)
    return p


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def sofia_ctx():
    return _login(SOFIA_EMAIL, SOFIA_PW)


@pytest.fixture(scope="module")
def parent_ctx():
    return _login(PARENT_EMAIL, PARENT_PW)


@pytest.fixture(scope="module")
def admin_ctx():
    return _login(ADMIN_EMAIL, ADMIN_PW)


# ===========================================================================
# 1) W9_ENCRYPTION_KEYS picked up from env
# ===========================================================================
class TestEnvKeys:
    def test_1_encryption_status_shows_env_key(self, admin_ctx):
        r = requests.get(
            f"{BASE}/api/admin/w9-encryption-status",
            headers=_auth(admin_ctx["access_token"]),
            timeout=15,
        )
        assert r.status_code == 200, r.text
        s = r.json()
        assert s["ephemeral_key"] is False, f"ephemeral_key should be False: {s}"
        assert s["keys_configured"] == 1, f"keys_configured should be 1: {s}"
        assert "records_total" in s
        assert "records_on_primary_key" in s
        assert "records_needing_rotation" in s


# ===========================================================================
# 2) Fernet on the write path
# ===========================================================================
class TestWritePathFernet:
    def test_2_post_writes_fernet_and_response_hides_encrypted(self, sofia_ctx):
        sofia_uid = sofia_ctx["user"]["id"]
        # Clean state so we can inspect the row
        _db.w9_forms.delete_many({"tutor_user_id": sofia_uid})

        r = requests.post(
            f"{BASE}/api/w9",
            headers=_auth(sofia_ctx["access_token"]),
            json=_valid_payload(
                tin="987-65-4321",
                legal_name="Sofía García",
                signature_name="Sofía García",
            ),
            timeout=15,
        )
        assert r.status_code == 201, f"POST /w9 expected 201, got {r.status_code} {r.text}"
        body = r.json()
        # Response body must not expose tin_encrypted
        assert "tin_encrypted" not in body or body["tin_encrypted"] in (None, ""), (
            f"tin_encrypted leaked in POST response: {body!r}"
        )
        assert body["tin_masked"].endswith("4321"), f"tin_masked wrong: {body['tin_masked']!r}"

        # GET /api/w9/me
        rg = requests.get(
            f"{BASE}/api/w9/me",
            headers=_auth(sofia_ctx["access_token"]),
            timeout=15,
        )
        assert rg.status_code == 200
        gbody = rg.json()
        assert "tin_encrypted" not in gbody or gbody["tin_encrypted"] in (None, ""), (
            f"tin_encrypted leaked on GET /w9/me: {gbody!r}"
        )
        assert gbody["tin_masked"].endswith("4321")

        # Inspect DB directly
        row = _db.w9_forms.find_one({"tutor_user_id": sofia_uid})
        assert row is not None, "row not persisted"
        token = row.get("tin_encrypted") or ""
        assert token.startswith("gAAAAA"), f"tin_encrypted must be Fernet (gAAAAA…), got: {token[:20]!r}"
        assert len(token) >= 60, f"Fernet token unexpectedly short ({len(token)}): {token!r}"
        assert "987654321" not in token, "raw digits leaked into tin_encrypted"


# ===========================================================================
# 3) Round-trip decryption via server.decrypt_tin
# ===========================================================================
class TestRoundTripDecrypt:
    def test_3_decrypt_tin_returns_raw_digits(self, sofia_ctx):
        sofia_uid = sofia_ctx["user"]["id"]
        row = _db.w9_forms.find_one({"tutor_user_id": sofia_uid})
        assert row is not None, "expected row from prior test — run test_2 first"
        token = row["tin_encrypted"]
        plain = server.decrypt_tin(token)
        assert plain == "987654321", f"round-trip decrypt failed, got {plain!r}"


# ===========================================================================
# 4) Encryption-status counts + admin-only guard
# ===========================================================================
class TestEncryptionStatusCounts:
    def test_4a_counts_after_post(self, admin_ctx):
        r = requests.get(
            f"{BASE}/api/admin/w9-encryption-status",
            headers=_auth(admin_ctx["access_token"]),
            timeout=15,
        )
        assert r.status_code == 200
        s = r.json()
        assert s["records_total"] >= 1, s
        assert s["records_on_primary_key"] == s["records_total"], (
            f"all records should be on primary key: {s}"
        )
        assert s["records_needing_rotation"] == 0, s

    def test_4b_parent_forbidden(self, parent_ctx):
        r = requests.get(
            f"{BASE}/api/admin/w9-encryption-status",
            headers=_auth(parent_ctx["access_token"]),
            timeout=15,
        )
        assert r.status_code == 403, f"parent should get 403, got {r.status_code} {r.text}"

    def test_4c_unauthenticated_401(self):
        r = requests.get(
            f"{BASE}/api/admin/w9-encryption-status",
            timeout=15,
        )
        assert r.status_code == 401, f"unauth should get 401, got {r.status_code} {r.text}"


# ===========================================================================
# 5) Legacy base64 fallback
# ===========================================================================
class TestLegacyFallback:
    def test_5_decrypt_tin_handles_base64_and_is_legacy_flags(self):
        legacy_token = base64.b64encode(b"555555555").decode()
        # Direct helper call
        assert server.decrypt_tin(legacy_token) == "555555555", (
            "decrypt_tin should fall back to base64 for legacy tokens"
        )
        assert server.is_legacy_tin_token(legacy_token) is True, (
            "is_legacy_tin_token should flag base64 tokens as legacy"
        )
        # And a fresh Fernet token is NOT legacy
        fresh = server.encrypt_tin("111223333")
        assert server.is_legacy_tin_token(fresh) is False
        assert server.decrypt_tin(fresh) == "111223333"

    def test_5b_insert_legacy_row_and_decrypt(self):
        """Insert a throw-away row with a legacy base64 token, verify decrypt_tin round-trips."""
        throwaway_uid = f"TEST_LEGACY_{uuid.uuid4().hex[:8]}"
        legacy_token = base64.b64encode(b"555555555").decode()
        try:
            _db.w9_forms.insert_one({
                "id": str(uuid.uuid4()),
                "tutor_user_id": throwaway_uid,
                "tutor_name": "Legacy Test",
                "tutor_email": "legacy@test.dev",
                "legal_name": "Legacy",
                "business_name": "",
                "tax_classification": "individual",
                "llc_tax_class": "",
                "other_classification": "",
                "address": "1 Legacy",
                "city": "Legacyville",
                "state": "CA",
                "zip_code": "00000",
                "country": "US",
                "tin_type": "ssn",
                "tin_masked": "•••••5555",
                "tin_encrypted": legacy_token,
                "signature_name": "Legacy",
                "is_us_person": True,
                "exempt_from_backup": False,
                "signed_at": "2024-01-01T00:00:00+00:00",
                "updated_at": "2024-01-01T00:00:00+00:00",
            })
            row = _db.w9_forms.find_one({"tutor_user_id": throwaway_uid})
            assert row["tin_encrypted"] == legacy_token
            assert server.decrypt_tin(row["tin_encrypted"]) == "555555555"
            assert server.is_legacy_tin_token(row["tin_encrypted"]) is True
        finally:
            _db.w9_forms.delete_many({"tutor_user_id": throwaway_uid})


# ===========================================================================
# 6) Startup migration idempotency
# ===========================================================================
class TestMigrationIdempotent:
    def test_6a_migration_leaves_fernet_row_untouched(self):
        throwaway_uid = f"TEST_MIGR_A_{uuid.uuid4().hex[:8]}"
        token = server.encrypt_tin("111223333")
        try:
            _db.w9_forms.insert_one({
                "id": str(uuid.uuid4()),
                "tutor_user_id": throwaway_uid,
                "tutor_name": "MigrA",
                "tutor_email": "migra@test.dev",
                "legal_name": "MigrA",
                "business_name": "",
                "tax_classification": "individual",
                "llc_tax_class": "",
                "other_classification": "",
                "address": "1", "city": "x", "state": "x", "zip_code": "00000", "country": "US",
                "tin_type": "ssn", "tin_masked": "•••••3333",
                "tin_encrypted": token,
                "signature_name": "MigrA",
                "is_us_person": True, "exempt_from_backup": False,
                "signed_at": "2024-01-01T00:00:00+00:00",
                "updated_at": "2024-01-01T00:00:00+00:00",
            })
            before = _db.w9_forms.find_one({"tutor_user_id": throwaway_uid})
            # Run migration (async)
            _run_on_persistent_loop(lambda: server._migrate_w9_tins())
            after = _db.w9_forms.find_one({"tutor_user_id": throwaway_uid})
            assert after["tin_encrypted"] == before["tin_encrypted"], (
                "Fresh Fernet token should be byte-identical after migration"
            )
            assert server.decrypt_tin(after["tin_encrypted"]) == "111223333"
        finally:
            _db.w9_forms.delete_many({"tutor_user_id": throwaway_uid})

    def test_6b_migration_rewrites_legacy_token(self):
        throwaway_uid = f"TEST_MIGR_B_{uuid.uuid4().hex[:8]}"
        legacy = base64.b64encode(b"444556666").decode()
        try:
            _db.w9_forms.insert_one({
                "id": str(uuid.uuid4()),
                "tutor_user_id": throwaway_uid,
                "tutor_name": "MigrB",
                "tutor_email": "migrb@test.dev",
                "legal_name": "MigrB",
                "business_name": "",
                "tax_classification": "individual",
                "llc_tax_class": "",
                "other_classification": "",
                "address": "1", "city": "x", "state": "x", "zip_code": "00000", "country": "US",
                "tin_type": "ssn", "tin_masked": "•••••6666",
                "tin_encrypted": legacy,
                "signature_name": "MigrB",
                "is_us_person": True, "exempt_from_backup": False,
                "signed_at": "2024-01-01T00:00:00+00:00",
                "updated_at": "2024-01-01T00:00:00+00:00",
            })
            _run_on_persistent_loop(lambda: server._migrate_w9_tins())
            after = _db.w9_forms.find_one({"tutor_user_id": throwaway_uid})
            assert after["tin_encrypted"] != legacy, "legacy token must be rewritten"
            assert after["tin_encrypted"].startswith("gAAAAA"), (
                f"after migration must be Fernet token, got: {after['tin_encrypted'][:20]!r}"
            )
            assert server.decrypt_tin(after["tin_encrypted"]) == "444556666"
            # Running again should be a no-op
            snapshot = after["tin_encrypted"]
            _run_on_persistent_loop(lambda: server._migrate_w9_tins())
            after2 = _db.w9_forms.find_one({"tutor_user_id": throwaway_uid})
            assert after2["tin_encrypted"] == snapshot, "second migration should not touch record"
        finally:
            _db.w9_forms.delete_many({"tutor_user_id": throwaway_uid})


# ===========================================================================
# 7) Unique index on tutor_user_id
# ===========================================================================
class TestUniqueIndex:
    def test_7_duplicate_insert_raises_duplicate_key(self):
        throwaway_uid = f"TEST_UNIQ_{uuid.uuid4().hex[:8]}"
        doc_template = {
            "tutor_user_id": throwaway_uid,
            "tutor_name": "Uniq",
            "tutor_email": "uniq@test.dev",
            "legal_name": "Uniq",
            "business_name": "",
            "tax_classification": "individual",
            "llc_tax_class": "",
            "other_classification": "",
            "address": "1", "city": "x", "state": "x", "zip_code": "00000", "country": "US",
            "tin_type": "ssn", "tin_masked": "•••••1111",
            "tin_encrypted": server.encrypt_tin("111111111"),
            "signature_name": "Uniq",
            "is_us_person": True, "exempt_from_backup": False,
            "signed_at": "2024-01-01T00:00:00+00:00",
            "updated_at": "2024-01-01T00:00:00+00:00",
        }
        try:
            _db.w9_forms.insert_one({"id": str(uuid.uuid4()), **doc_template})
            with pytest.raises(pymongo.errors.DuplicateKeyError):
                _db.w9_forms.insert_one({"id": str(uuid.uuid4()), **doc_template})
        finally:
            _db.w9_forms.delete_many({"tutor_user_id": throwaway_uid})
