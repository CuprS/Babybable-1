"""
Session-7 backend feature tests for Babybabel — W-9 tax form.

Coverage:
1) Signup fresh tutor → POST /api/w9 returns 201 (no completed-session gate on POST).
2) Parent role → POST /api/w9 returns 403.
3) Payload validation on POST /api/w9:
   - tax_classification="alien" → 422
   - tin has fewer than 9 digits → 422
   - tin_type="itin" → 422
   - missing required legal_name → 422
4) Happy path for Sofía:
   - POST → 201, tin_masked ends with last-4, tin_encrypted NOT in body
   - GET /api/w9/me returns same doc, no tin_encrypted
   - GET /api/admin/w9 (as admin) contains Sofía's entry
   - GET /api/admin/w9/{sofia_uid} returns her doc
   - GET /api/admin/w9/{sofia_uid} as parent → 403
5) Notification wiring:
   - Inject a paid booking in the past (>70 min ago) for Sofía
   - GET /api/notifications as Sofía → includes kind="w9:required"
   - GET /api/notifications again → no duplicate
   - POST /api/w9 → notification's read=true in db.notifications
6) Status endpoint:
   - {required:true, submitted:false, completed_session:true} after past paid booking, before form
   - {required:false, submitted:true, completed_session:true} after form filed
   - {required:false, submitted:false, completed_session:false} for a brand-new tutor
7) Upsert semantics:
   - Re-POST with different data → same id; signed_at preserved; updated_at bumped
"""
import os
import uuid
import base64
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
ADMIN_EMAIL = "copperstone17@gmail.com"
ADMIN_PW = "REDACTED-PASSWORD"

NOTE_TAG = "TEST_SESSION7"


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


def _signup(name, email, password, role="tutor"):
    r = requests.post(
        f"{BASE}/api/auth/signup",
        json={"name": name, "email": email, "password": password, "role": role},
        timeout=15,
    )
    return r


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
    data = _login(SOFIA_EMAIL, SOFIA_PW)
    return {"token": data["access_token"], "user": data["user"]}


@pytest.fixture(scope="module")
def parent_ctx():
    data = _login(PARENT_EMAIL, PARENT_PW)
    return {"token": data["access_token"], "user": data["user"]}


@pytest.fixture(scope="module")
def admin_ctx():
    data = _login(ADMIN_EMAIL, ADMIN_PW)
    return {"token": data["access_token"], "user": data["user"]}


@pytest.fixture(scope="module")
def sofia_tutor_doc(sofia_ctx):
    doc = _db.tutors.find_one({"user_id": sofia_ctx["user"]["id"]}, {"_id": 0})
    assert doc, "Sofia tutor doc missing"
    return doc


@pytest.fixture(scope="module", autouse=True)
def _clean_slate(sofia_ctx):
    """Wipe Sofía's W-9 + w9:required notifs + TEST_SESSION7 bookings so tests
    start from a clean state; repeat teardown."""
    uid = sofia_ctx["user"]["id"]
    _db.w9_forms.delete_many({"tutor_user_id": uid})
    _db.notifications.delete_many({"user_id": uid, "kind": {"$regex": "^w9:"}})
    _db.bookings.delete_many({"tutor_id": {"$exists": True}, "notes": {"$regex": f"^{NOTE_TAG}"}})
    yield
    _db.w9_forms.delete_many({"tutor_user_id": uid})
    _db.notifications.delete_many({"user_id": uid, "kind": {"$regex": "^w9:"}})
    _db.bookings.delete_many({"tutor_id": {"$exists": True}, "notes": {"$regex": f"^{NOTE_TAG}"}})


def _inject_paid_past_booking(parent_uid, tutor_doc, minutes_ago=90):
    when = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    booking = {
        "id": str(uuid.uuid4()),
        "parent_id": parent_uid,
        "parent_name": "Test Parent",
        "tutor_id": tutor_doc["id"],
        "tutor_name": tutor_doc["name"],
        "date": when.date().isoformat(),
        "time": f"{when.hour:02d}:{when.minute:02d}",
        "duration_minutes": 60,
        "language": "Spanish",
        "amount_cents": 3535,
        "platform_fee_cents": 35,
        "currency": tutor_doc.get("currency", "usd"),
        "payment_status": "paid",
        "stripe_payment_intent_id": f"pi_mock_{uuid.uuid4()}",
        "client_secret": None,
        "notes": f"{NOTE_TAG}_past",
        "is_au_pair": False,
        "lessons_count": 1,
        "distance_miles": None,
        "remote": True,
        "housing_offered": "",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _db.bookings.insert_one(dict(booking))
    return booking


# ===========================================================================
# 1) Fresh tutor → POST /api/w9 allowed (returns 201)
# ===========================================================================
class TestFreshTutorCanPost:
    def test_1_new_tutor_no_bookings_can_post(self):
        email = f"freshw9_{uuid.uuid4().hex[:8]}@babybabel.dev"
        r = _signup("Fresh W9 Tutor", email, "password123", role="tutor")
        assert r.status_code == 201, f"signup failed: {r.status_code} {r.text}"
        token = r.json()["access_token"]
        uid = r.json()["user"]["id"]
        try:
            rp = requests.post(
                f"{BASE}/api/w9",
                headers=_auth(token),
                json=_valid_payload(legal_name="Fresh W9 Tutor",
                                    signature_name="Fresh W9 Tutor"),
                timeout=15,
            )
            assert rp.status_code == 201, f"expected 201 for new tutor POST /w9, got {rp.status_code} {rp.text}"
            body = rp.json()
            assert body["tutor_user_id"] == uid
            assert "tin_encrypted" not in body or body["tin_encrypted"] is None, (
                f"tin_encrypted must NOT be present in response body: {body}"
            )
            assert body["tin_masked"].endswith("6789")
        finally:
            _db.w9_forms.delete_many({"tutor_user_id": uid})
            _db.users.delete_many({"id": uid})
            _db.tutors.delete_many({"user_id": uid})
            _db.notifications.delete_many({"user_id": uid})


# ===========================================================================
# 2) Parent → POST /api/w9 → 403
# ===========================================================================
class TestParentForbidden:
    def test_2_parent_cannot_post_w9(self, parent_ctx):
        r = requests.post(
            f"{BASE}/api/w9",
            headers=_auth(parent_ctx["token"]),
            json=_valid_payload(),
            timeout=15,
        )
        assert r.status_code == 403, f"parent POST /w9 expected 403, got {r.status_code} {r.text}"


# ===========================================================================
# 3) Payload validation → 422
# ===========================================================================
class TestPayloadValidation:
    def test_3a_bad_tax_classification(self, sofia_ctx):
        r = requests.post(
            f"{BASE}/api/w9",
            headers=_auth(sofia_ctx["token"]),
            json=_valid_payload(tax_classification="alien"),
            timeout=15,
        )
        assert r.status_code == 422, f"bad classification expected 422, got {r.status_code} {r.text}"

    def test_3b_tin_fewer_than_9_digits(self, sofia_ctx):
        r = requests.post(
            f"{BASE}/api/w9",
            headers=_auth(sofia_ctx["token"]),
            json=_valid_payload(tin="123-45-abcd"),
            timeout=15,
        )
        assert r.status_code == 422, f"short tin expected 422, got {r.status_code} {r.text}"

    def test_3c_bad_tin_type(self, sofia_ctx):
        r = requests.post(
            f"{BASE}/api/w9",
            headers=_auth(sofia_ctx["token"]),
            json=_valid_payload(tin_type="itin"),
            timeout=15,
        )
        assert r.status_code == 422, f"bad tin_type expected 422, got {r.status_code} {r.text}"

    def test_3d_missing_legal_name(self, sofia_ctx):
        payload = _valid_payload()
        payload.pop("legal_name")
        r = requests.post(
            f"{BASE}/api/w9",
            headers=_auth(sofia_ctx["token"]),
            json=payload,
            timeout=15,
        )
        assert r.status_code == 422, f"missing legal_name expected 422, got {r.status_code} {r.text}"


# ===========================================================================
# 4) Happy path for Sofía
# ===========================================================================
class TestSofiaHappyPath:
    def test_4a_sofia_post_returns_masked_tin_no_encrypted(self, sofia_ctx):
        r = requests.post(
            f"{BASE}/api/w9",
            headers=_auth(sofia_ctx["token"]),
            json=_valid_payload(tin="987-65-4321", legal_name="Sofía García",
                                signature_name="Sofía García"),
            timeout=15,
        )
        assert r.status_code == 201, f"POST /w9 expected 201, got {r.status_code} {r.text}"
        b = r.json()
        assert b["tin_masked"].endswith("4321"), f"tin_masked wrong: {b['tin_masked']!r}"
        # Ensure the mask hides everything but the last 4
        assert "9876" not in b["tin_masked"], f"tin leaked in mask: {b['tin_masked']!r}"
        assert b.get("tin_encrypted") in (None, ""), (
            f"tin_encrypted must NOT be exposed, got: {b.get('tin_encrypted')!r}"
        )
        assert b["tutor_user_id"] == sofia_ctx["user"]["id"]
        assert b["signed_at"], "signed_at missing"
        assert b["updated_at"], "updated_at missing"

    def test_4b_get_me_returns_same_doc_no_encrypted(self, sofia_ctx):
        r = requests.get(
            f"{BASE}/api/w9/me",
            headers=_auth(sofia_ctx["token"]),
            timeout=15,
        )
        assert r.status_code == 200, r.text
        b = r.json()
        assert b is not None, "expected doc, got null"
        assert b["tin_masked"].endswith("4321")
        assert b.get("tin_encrypted") in (None, ""), (
            f"tin_encrypted leaked: {b.get('tin_encrypted')!r}"
        )

    def test_4c_admin_list_contains_sofia(self, sofia_ctx, admin_ctx):
        r = requests.get(
            f"{BASE}/api/admin/w9",
            headers=_auth(admin_ctx["token"]),
            timeout=15,
        )
        assert r.status_code == 200, r.text
        items = r.json()
        assert isinstance(items, list) and len(items) >= 1
        uid = sofia_ctx["user"]["id"]
        match = next((x for x in items if x["tutor_user_id"] == uid), None)
        assert match is not None, "Sofía's W-9 missing from admin list"
        assert match.get("tin_encrypted") in (None, "")
        # Sorted by updated_at desc → Sofia (just now) should be at (or near) top
        assert items[0]["tutor_user_id"] == uid, (
            f"expected Sofia at top by updated_at, got {items[0]['tutor_user_id']}"
        )

    def test_4d_admin_get_by_uid(self, sofia_ctx, admin_ctx):
        uid = sofia_ctx["user"]["id"]
        r = requests.get(
            f"{BASE}/api/admin/w9/{uid}",
            headers=_auth(admin_ctx["token"]),
            timeout=15,
        )
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["tutor_user_id"] == uid
        assert b.get("tin_encrypted") in (None, "")

    def test_4e_parent_forbidden_admin_endpoint(self, sofia_ctx, parent_ctx):
        uid = sofia_ctx["user"]["id"]
        r = requests.get(
            f"{BASE}/api/admin/w9/{uid}",
            headers=_auth(parent_ctx["token"]),
            timeout=15,
        )
        assert r.status_code == 403, f"parent hitting admin /w9/{{uid}} expected 403, got {r.status_code} {r.text}"


# ===========================================================================
# 5) Notification wiring
# ===========================================================================
class TestNotificationWiring:
    def test_5_w9_required_notif_and_read_flip(self, sofia_ctx, parent_ctx, sofia_tutor_doc):
        sofia_uid = sofia_ctx["user"]["id"]
        # Clean state: no w9_forms, no w9:required notif
        _db.w9_forms.delete_many({"tutor_user_id": sofia_uid})
        _db.notifications.delete_many({"user_id": sofia_uid, "kind": {"$regex": "^w9:"}})
        # Inject a paid past booking so tutor_has_completed_session returns True
        b = _inject_paid_past_booking(parent_ctx["user"]["id"], sofia_tutor_doc, minutes_ago=90)
        try:
            # First GET /api/notifications as Sofía → w9:required present
            r1 = requests.get(
                f"{BASE}/api/notifications",
                headers=_auth(sofia_ctx["token"]),
                timeout=15,
            )
            assert r1.status_code == 200, r1.text
            notifs = r1.json()
            w9s = [n for n in notifs if n.get("kind") == "w9:required"]
            assert len(w9s) == 1, (
                f"expected 1 w9:required notif, got {len(w9s)}. kinds={[n.get('kind') for n in notifs]}"
            )
            assert w9s[0]["read"] is False, f"new w9:required notif should be unread: {w9s[0]}"

            # Second GET → still exactly one (dedupe on kind)
            r2 = requests.get(
                f"{BASE}/api/notifications",
                headers=_auth(sofia_ctx["token"]),
                timeout=15,
            )
            assert r2.status_code == 200
            w9s2 = [n for n in r2.json() if n.get("kind") == "w9:required"]
            assert len(w9s2) == 1, f"w9:required duplicated: {len(w9s2)}"

            # POST W-9 → notif flips to read=true
            rp = requests.post(
                f"{BASE}/api/w9",
                headers=_auth(sofia_ctx["token"]),
                json=_valid_payload(legal_name="Sofía García",
                                    signature_name="Sofía García",
                                    tin="111-22-3333"),
                timeout=15,
            )
            assert rp.status_code == 201, f"POST /w9 failed: {rp.status_code} {rp.text}"

            # Query mongo directly
            stored = list(_db.notifications.find(
                {"user_id": sofia_uid, "kind": "w9:required"}, {"_id": 0}
            ))
            assert len(stored) == 1, f"expected 1 stored w9:required notif, got {len(stored)}"
            assert stored[0]["read"] is True, f"notif should be read=True after POST, got {stored[0]}"
        finally:
            _db.bookings.delete_one({"id": b["id"]})


# ===========================================================================
# 6) Status endpoint
# ===========================================================================
class TestStatusEndpoint:
    def test_6a_required_true_after_past_booking_before_form(
        self, sofia_ctx, parent_ctx, sofia_tutor_doc
    ):
        sofia_uid = sofia_ctx["user"]["id"]
        _db.w9_forms.delete_many({"tutor_user_id": sofia_uid})
        _db.notifications.delete_many({"user_id": sofia_uid, "kind": {"$regex": "^w9:"}})
        b = _inject_paid_past_booking(parent_ctx["user"]["id"], sofia_tutor_doc, minutes_ago=120)
        try:
            r = requests.get(
                f"{BASE}/api/w9/me/status",
                headers=_auth(sofia_ctx["token"]),
                timeout=15,
            )
            assert r.status_code == 200, r.text
            s = r.json()
            assert s["required"] is True, s
            assert s["submitted"] is False, s
            assert s["completed_session"] is True, s
            # first_booking_id is the EARLIEST completed paid booking; there may be pre-existing
            # ones from prior test sessions, so just assert it's truthy.
            assert s.get("first_booking_id"), (
                f"expected first_booking_id to be truthy, got {s.get('first_booking_id')!r}"
            )
        finally:
            _db.bookings.delete_one({"id": b["id"]})

    def test_6b_submitted_true_after_form_filed(
        self, sofia_ctx, parent_ctx, sofia_tutor_doc
    ):
        sofia_uid = sofia_ctx["user"]["id"]
        _db.w9_forms.delete_many({"tutor_user_id": sofia_uid})
        b = _inject_paid_past_booking(parent_ctx["user"]["id"], sofia_tutor_doc, minutes_ago=120)
        try:
            rp = requests.post(
                f"{BASE}/api/w9",
                headers=_auth(sofia_ctx["token"]),
                json=_valid_payload(tin="222-33-4444"),
                timeout=15,
            )
            assert rp.status_code == 201, rp.text
            r = requests.get(
                f"{BASE}/api/w9/me/status",
                headers=_auth(sofia_ctx["token"]),
                timeout=15,
            )
            assert r.status_code == 200
            s = r.json()
            assert s["required"] is False, s
            assert s["submitted"] is True, s
            assert s["completed_session"] is True, s
        finally:
            _db.bookings.delete_one({"id": b["id"]})
            _db.w9_forms.delete_many({"tutor_user_id": sofia_uid})

    def test_6c_fresh_tutor_all_false(self):
        email = f"fresh_status_{uuid.uuid4().hex[:8]}@babybabel.dev"
        r = _signup("Fresh Status", email, "password123", role="tutor")
        assert r.status_code == 201, r.text
        token = r.json()["access_token"]
        uid = r.json()["user"]["id"]
        try:
            rs = requests.get(
                f"{BASE}/api/w9/me/status",
                headers=_auth(token),
                timeout=15,
            )
            assert rs.status_code == 200, rs.text
            s = rs.json()
            assert s["required"] is False, s
            assert s["submitted"] is False, s
            assert s["completed_session"] is False, s
        finally:
            _db.users.delete_many({"id": uid})
            _db.tutors.delete_many({"user_id": uid})


# ===========================================================================
# 7) Upsert semantics
# ===========================================================================
class TestUpsertSemantics:
    def test_7_repost_updates_same_doc_preserves_signed_at(self, sofia_ctx):
        sofia_uid = sofia_ctx["user"]["id"]
        _db.w9_forms.delete_many({"tutor_user_id": sofia_uid})

        # First POST
        r1 = requests.post(
            f"{BASE}/api/w9",
            headers=_auth(sofia_ctx["token"]),
            json=_valid_payload(
                legal_name="Sofía García",
                signature_name="Sofía García",
                tin="555-66-7777",
                address="Old Street 1",
                city="Madrid",
            ),
            timeout=15,
        )
        assert r1.status_code == 201, r1.text
        doc1 = r1.json()
        # Second POST with different data
        r2 = requests.post(
            f"{BASE}/api/w9",
            headers=_auth(sofia_ctx["token"]),
            json=_valid_payload(
                legal_name="Sofía García Updated",
                signature_name="Sofía García Updated",
                tin="888-99-0000",
                address="New Street 42",
                city="Barcelona",
                tax_classification="llc",
                llc_tax_class="c",
            ),
            timeout=15,
        )
        assert r2.status_code == 201, r2.text
        doc2 = r2.json()
        # Same id preserved
        assert doc1["id"] == doc2["id"], f"id changed on upsert: {doc1['id']} vs {doc2['id']}"
        # signed_at preserved
        assert doc1["signed_at"] == doc2["signed_at"], (
            f"signed_at should be preserved: {doc1['signed_at']} → {doc2['signed_at']}"
        )
        # updated_at bumped (>= first)
        assert doc2["updated_at"] >= doc1["updated_at"], (
            f"updated_at should advance: {doc1['updated_at']} → {doc2['updated_at']}"
        )
        # Fields updated
        assert doc2["legal_name"] == "Sofía García Updated"
        assert doc2["city"] == "Barcelona"
        assert doc2["address"] == "New Street 42"
        assert doc2["tax_classification"] == "llc"
        assert doc2["llc_tax_class"] == "C", f"llc_tax_class should be uppercased: {doc2['llc_tax_class']!r}"
        assert doc2["tin_masked"].endswith("0000")
        # Only one doc in db
        cnt = _db.w9_forms.count_documents({"tutor_user_id": sofia_uid})
        assert cnt == 1, f"upsert produced {cnt} docs, expected 1"
