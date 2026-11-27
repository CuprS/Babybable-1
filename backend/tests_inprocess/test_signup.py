"""Creating an account: consent, input checks, duplicates, and the email confirmation step."""
import hashlib
import uuid

import core


def _body(**over) -> dict:
    b = {"email": f"new-{uuid.uuid4().hex[:8]}@example.com", "password": "longenough1", "name": "Pat Parent",
         "role": "parent", "accept_terms": True, "timezone": "America/Chicago"}
    b.update(over)
    return b


def test_parent_and_tutor_can_sign_up(client, db_call):
    for role in ("parent", "tutor"):
        b = _body(role=role)
        r = client.post("/api/auth/signup", json=b)
        assert r.status_code == 201, r.text
        user = r.json()["user"]
        assert user["role"] == role and user["email_verified"] is False and user["timezone"] == "America/Chicago"
        assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}).status_code == 200
    # A tutor gets an (empty, unverified) profile to fill in next.
    t = db_call(core.db.tutors.find_one, {"user_id": user["id"]})
    assert t and t["verification_status"] == "none" and t["languages"] == []


def test_terms_must_be_accepted_and_are_recorded(client, db_call):
    assert client.post("/api/auth/signup", json=_body(accept_terms=False)).status_code == 400
    b = _body()
    r = client.post("/api/auth/signup", json={k: v for k, v in b.items() if k != "accept_terms"})
    assert r.status_code == 400
    r = client.post("/api/auth/signup", json=b)
    doc = db_call(core.db.users.find_one, {"id": r.json()["user"]["id"]})
    assert doc["terms_accepted_at"] and doc["terms_version"]


def test_input_checks(client):
    assert client.post("/api/auth/signup", json=_body(password="short")).status_code == 422
    assert client.post("/api/auth/signup", json=_body(name="   ")).status_code == 422
    assert client.post("/api/auth/signup", json=_body(email="not-an-email")).status_code == 422
    assert client.post("/api/auth/signup", json=_body(role="admin")).status_code == 400
    b = _body()
    assert client.post("/api/auth/signup", json={**b, "password": b["email"].split("@")[0]}).status_code == 400
    r = client.post("/api/auth/signup", json=_body(name="  Pat    Parent "))
    assert r.json()["user"]["name"] == "Pat Parent"


def test_same_email_twice_is_refused_whatever_the_case(client):
    b = _body()
    assert client.post("/api/auth/signup", json=b).status_code == 201
    r = client.post("/api/auth/signup", json={**b, "email": "  " + b["email"].upper()})
    assert r.status_code in (400, 422)
    assert "logging in" in r.text or r.status_code == 422


def test_email_confirmation_code(client, db_call):
    r = client.post("/api/auth/signup", json=_body())
    tok, uid = r.json()["access_token"], r.json()["user"]["id"]
    h = {"Authorization": f"Bearer {tok}"}
    # A code was issued at signup; the test can't read the email, so it plants a known one.
    assert db_call(core.db.auth_codes.find_one, {"user_id": uid, "purpose": "verify"})
    db_call(core.db.auth_codes.update_one, {"user_id": uid, "purpose": "verify"},
            {"$set": {"code_hash": hashlib.sha256(b"112233").hexdigest()}})
    assert client.post("/api/auth/verify-email", headers=h, json={"code": "000000"}).status_code == 400
    r = client.post("/api/auth/verify-email", headers=h, json={"code": "112233"})
    assert r.status_code == 200 and r.json()["email_verified"] is True
