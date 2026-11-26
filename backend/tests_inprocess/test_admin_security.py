"""The admin account: password + emailed code to sign in, short sessions, no email reset, and
not reachable by the public. Each test is an attack attempt that must keep failing."""
import hashlib
import uuid

import pytest

import core

PASSWORD = "admin-test-password-1"
CODE = "135790"


def H(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture
def admin(db_call):
    email = f"admin-{uuid.uuid4().hex[:8]}@example.com"
    doc = {"id": str(uuid.uuid4()), "email": email, "password_hash": core.hash_password(PASSWORD), "name": "Admin",
           "role": "admin", "is_admin": True, "email_verified": True, "created_at": core.now_iso()}
    db_call(core.db.users.insert_one, dict(doc))
    return doc


def _known_code(db_call, admin):
    """The test can't read the email, so it swaps the stored (hashed) code for a known one."""
    db_call(core.db.auth_codes.update_one, {"user_id": admin["id"], "purpose": "admin_login"},
            {"$set": {"code_hash": hashlib.sha256(CODE.encode()).hexdigest(), "attempts": 0}})


def _sign_in(client, db_call, admin) -> str:
    first = client.post("/api/auth/login", json={"email": admin["email"], "password": PASSWORD})
    assert first.status_code == 428
    _known_code(db_call, admin)
    r = client.post("/api/auth/login", json={"email": admin["email"], "password": PASSWORD, "code": CODE})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_admin_password_alone_does_not_sign_in(client, admin):
    r = client.post("/api/auth/login", json={"email": admin["email"], "password": PASSWORD})
    assert r.status_code == 428 and "access_token" not in r.text
    assert client.post("/api/auth/login", json={"email": admin["email"], "password": PASSWORD, "code": "000000"}).status_code == 400


def test_admin_sign_in_with_code_works(client, db_call, admin):
    tok = _sign_in(client, db_call, admin)
    assert client.get("/api/admin/stats", headers=H(tok)).status_code == 200
    # The code works once only.
    assert client.post("/api/auth/login", json={"email": admin["email"], "password": PASSWORD, "code": CODE}).status_code == 400


def test_code_guessing_is_capped(client, db_call, admin):
    client.post("/api/auth/login", json={"email": admin["email"], "password": PASSWORD})
    _known_code(db_call, admin)
    for _ in range(core.CODE_MAX_ATTEMPTS if hasattr(core, "CODE_MAX_ATTEMPTS") else 5):
        client.post("/api/auth/login", json={"email": admin["email"], "password": PASSWORD, "code": "999999"})
    # Even the right code no longer works after too many wrong tries.
    assert client.post("/api/auth/login", json={"email": admin["email"], "password": PASSWORD, "code": CODE}).status_code in (400, 429)


def test_tokens_not_from_the_admin_sign_in_are_refused(client, admin):
    plain = core.make_token(admin["id"], "admin")  # e.g. from signup or a password reset
    assert client.get("/api/admin/stats", headers=H(plain)).status_code == 401


def test_admin_sessions_expire_sooner(client, db_call, admin, monkeypatch):
    tok = _sign_in(client, db_call, admin)
    monkeypatch.setattr(core, "ADMIN_SESSION_MINUTES", -1)  # pretend the 12 hours have passed
    assert client.get("/api/admin/stats", headers=H(tok)).status_code == 401


def test_admin_password_cannot_be_reset_by_email(client, db_call, admin):
    assert client.post("/api/auth/forgot-password", json={"email": admin["email"]}).json()["ok"] is True
    assert db_call(core.db.auth_codes.find_one, {"user_id": admin["id"], "purpose": "reset"}) is None
    # Even with a planted reset code, the reset is refused.
    db_call(core.db.auth_codes.insert_one, {"user_id": admin["id"], "purpose": "reset", "attempts": 0,
                                            "code_hash": hashlib.sha256(CODE.encode()).hexdigest(),
                                            "expires_at": "2999-01-01T00:00:00+00:00"})
    r = client.post("/api/auth/reset-password", json={"email": admin["email"], "code": CODE, "new_password": "taken-over-123"})
    assert r.status_code == 400


def test_nobody_can_sign_up_as_admin(client):
    r = client.post("/api/auth/signup", json={"email": "x@example.com", "password": "longenough1", "name": "X", "role": "admin"})
    assert r.status_code == 400


def test_public_cannot_message_the_admin_first(client, db_call, admin, make_user):
    p = make_user()
    r = client.post("/api/messages", headers=p["h"], json={"to_user_id": admin["id"], "text": "hello admin"})
    assert r.status_code == 404
    # Once the admin writes (e.g. about a safety report), the person can reply.
    tok = _sign_in(client, db_call, admin)
    assert client.post("/api/messages", headers=H(tok), json={"to_user_id": p["user"]["id"], "text": "About your report"}).status_code == 200
    assert client.post("/api/messages", headers=p["h"], json={"to_user_id": admin["id"], "text": "Thanks"}).status_code == 200


def test_regular_users_cannot_use_admin_tools(client, make_user):
    p = make_user()
    for path in ("/api/admin/stats", "/api/admin/users", "/api/admin/earnings", "/api/admin/events"):
        assert client.get(path, headers=p["h"]).status_code == 403
        assert client.get(path).status_code == 401
