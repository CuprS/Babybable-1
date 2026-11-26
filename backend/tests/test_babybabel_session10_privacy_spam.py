# Session 10: security hardening — family privacy, message spam caps, cold-message cap,
# file token-in-URL removal, CORS origin restriction.
# Users are seeded directly in Mongo + JWTs minted with backend JWT_SECRET to avoid the
# per-IP signup/login rate limits (5 signups / 10 min).
import os
import io
import uuid
from datetime import datetime, timezone, timedelta

import jwt
import pytest
import requests

from _support import backend_env, backend_url, mongo_db  # noqa: E402
from _support import admin_session  # noqa: E402

BASE_URL = backend_url()
DB = mongo_db()
BENV = backend_env()
CREATED_USERS: list = []

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7\x35\x81\x84\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _token(uid, role):
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": uid, "role": role, "iat": now, "exp": now + timedelta(hours=2)},
                      BENV["JWT_SECRET"], algorithm=BENV.get("JWT_ALGORITHM") or "HS256")


def make_user(role, with_profile=False):
    uid = str(uuid.uuid4())
    name = f"TEST_{role}_{uid[:6]}"
    DB.users.insert_one({"id": uid, "email": f"test_{uid[:8]}@test.dev", "password_hash": "x",
                         "name": name, "role": role, "avatar_url": None,
                         "created_at": datetime.now(timezone.utc).isoformat()})
    tutor_id = None
    if role == "tutor":
        tutor_id = str(uuid.uuid4())
        DB.tutors.insert_one({"id": tutor_id, "user_id": uid, "name": name, "languages": ["Spanish"],
                              "hourly_rate_cents": 3000, "currency": "usd", "weekly_availability": {},
                              "created_at": datetime.now(timezone.utc).isoformat()})
    if role == "parent" and with_profile:
        DB.parents.insert_one({"user_id": uid, "name": name, "city": "Austin, TX",
                               "latitude": 30.2672, "longitude": -97.7431,
                               "children": [{"id": str(uuid.uuid4()), "name": "Kiddo", "age": 5, "avatar_url": "x/kid.png"}]})
    CREATED_USERS.append(uid)
    return {"id": uid, "tok": _token(uid, role), "tutor_id": tutor_id, "role": role}


def H(u):
    return {"Authorization": f"Bearer {u['tok']}"}


def send(frm, to, text="hello"):
    return requests.post(f"{BASE_URL}/api/messages", json={"to_user_id": to["id"], "text": text}, headers=H(frm), timeout=30)


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    yield
    for uid in CREATED_USERS:
        DB.messages.delete_many({"$or": [{"from_user_id": uid}, {"to_user_id": uid}]})
        DB.bookings.delete_many({"parent_id": uid})
        DB.parents.delete_many({"user_id": uid})
        DB.tutors.delete_many({"user_id": uid})
        DB.notifications.delete_many({"user_id": uid})
        DB.users.delete_many({"id": uid})


def _login(email, pw):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": pw}, timeout=30)
    if r.status_code != 200:
        pytest.skip(f"login failed {r.status_code}")
    return r.json()


# ---- Family privacy: GET /api/parents/{id}/public ----
class TestParentPublicPrivacy:
    def test_owner_sees_coords(self):
        p = make_user("parent", with_profile=True)
        r = requests.get(f"{BASE_URL}/api/parents/{p['id']}/public", headers=H(p), timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["latitude"] == 30.2672 and d["longitude"] == -97.7431
        assert d["children"][0]["avatar_url"] == "x/kid.png"

    def test_admin_sees_profile(self):
        p = make_user("parent", with_profile=True)
        a = admin_session()
        r = requests.get(f"{BASE_URL}/api/parents/{p['id']}/public",
                         headers={"Authorization": f"Bearer {a['access_token']}"}, timeout=30)
        assert r.status_code == 200, r.text
        assert r.json()["city"] == "Austin, TX"
        assert r.json()["latitude"] is None  # admin is non-owner -> stripped

    def test_unrelated_tutor_403(self):
        p = make_user("parent", with_profile=True)
        t = make_user("tutor")
        r = requests.get(f"{BASE_URL}/api/parents/{p['id']}/public", headers=H(t), timeout=30)
        assert r.status_code == 403, r.text
        assert "only visible" in r.json()["detail"]

    def test_cold_message_then_reply_flow(self):
        p = make_user("parent", with_profile=True)
        t = make_user("tutor")
        assert send(t, p, "Hi family").status_code == 200
        r = requests.get(f"{BASE_URL}/api/parents/{p['id']}/public", headers=H(t), timeout=30)
        assert r.status_code == 403, f"cold-only tutor should be 403: {r.status_code} {r.text}"
        assert send(p, t, "Hi tutor").status_code == 200
        r = requests.get(f"{BASE_URL}/api/parents/{p['id']}/public", headers=H(t), timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["latitude"] is None and d["longitude"] is None
        assert d["city"] == "Austin, TX"
        assert d["children"][0]["name"] == "Kiddo" and d["children"][0]["avatar_url"] is None

    def test_tutor_with_booking_200(self):
        p = make_user("parent", with_profile=True)
        t = make_user("tutor")
        DB.tutors.update_one({"id": t["tutor_id"]}, {"$set": {"allows_remote": True}})
        b = requests.post(f"{BASE_URL}/api/bookings", json={"tutor_id": t["tutor_id"], "date": "2030-01-15",
                          "time": "10:00", "duration_minutes": 60, "language": "Spanish"}, headers=H(p), timeout=60)
        assert b.status_code == 200, b.text
        r = requests.get(f"{BASE_URL}/api/parents/{p['id']}/public", headers=H(t), timeout=30)
        assert r.status_code == 200, r.text
        assert r.json()["latitude"] is None

    def test_other_parent_403(self):
        p = make_user("parent", with_profile=True)
        p2 = make_user("parent")
        # even if they chatted
        send(p, p2, "hey")
        send(p2, p, "hey back")
        r = requests.get(f"{BASE_URL}/api/parents/{p['id']}/public", headers=H(p2), timeout=30)
        assert r.status_code == 403, r.text

    def test_anon_401(self):
        p = make_user("parent", with_profile=True)
        r = requests.get(f"{BASE_URL}/api/parents/{p['id']}/public", timeout=30)
        assert r.status_code == 401


# ---- Message rate limits ----
class TestMessageRateLimits:
    def test_21st_message_in_minute_429(self):
        a = make_user("parent")
        b = make_user("tutor")
        for i in range(20):
            r = send(a, b, f"msg {i}")
            assert r.status_code == 200, f"msg {i}: {r.status_code} {r.text}"
        r = send(a, b, "msg 21")
        assert r.status_code == 429, r.text
        assert "very quickly" in r.json()["detail"]
        assert r.headers.get("Retry-After") == "60"

    def test_invitations_count_toward_minute_cap(self):
        t = make_user("tutor")
        p = make_user("parent")
        assert send(p, t, "hello").status_code == 200  # make relationship (not cold)
        for i in range(20):
            r = send(t, p, f"m{i}")
            assert r.status_code == 200, r.text
        r = requests.post(f"{BASE_URL}/api/messages/invitation", json={"to_user_id": p["id"], "price_cents": 3000,
                          "date": "2030-01-15", "time": "10:00", "duration_minutes": 60, "language": "Spanish"},
                          headers=H(t), timeout=30)
        assert r.status_code == 429, r.text

    def test_daily_cap_300(self):
        a = make_user("parent")
        b = make_user("tutor")
        old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        DB.messages.insert_many([{"id": str(uuid.uuid4()), "from_user_id": a["id"], "to_user_id": b["id"],
                                  "text": "seed", "kind": "text", "invitation": None, "created_at": old, "cold": False}
                                 for _ in range(300)])
        r = send(a, b, "301st")
        assert r.status_code == 429, r.text
        assert "Daily limit of 300" in r.json()["detail"]


# ---- Cold message cap ----
class TestColdMessageCap:
    def test_cold_cap(self):
        t = make_user("tutor")
        parents = [make_user("parent") for _ in range(11)]
        for i, p in enumerate(parents[:10]):
            r = send(t, p, f"hi {i}")
            assert r.status_code == 200, f"parent {i}: {r.status_code} {r.text}"
        r = send(t, parents[10], "hi 11")
        assert r.status_code == 429, r.text
        assert "You can contact 10 new families per day" in r.json()["detail"]
        # already-contacted parent still works
        r = send(t, parents[0], "follow-up")
        assert r.status_code == 200, r.text
        # cold invitation to 11th parent also blocked
        r = requests.post(f"{BASE_URL}/api/messages/invitation", json={"to_user_id": parents[10]["id"], "price_cents": 3000,
                          "date": "2030-01-15", "time": "10:00", "duration_minutes": 60, "language": "Spanish"},
                          headers=H(t), timeout=30)
        assert r.status_code == 429, r.text
        # parent reaching out to tutor (11th parent) is never cold and opens relationship
        r = send(parents[10], t, "hi tutor")
        assert r.status_code == 200, r.text
        r = send(t, parents[10], "thanks for reaching out")
        assert r.status_code == 200, r.text

    def test_parent_to_tutor_never_cold(self):
        p = make_user("parent")
        tutors = [make_user("tutor") for _ in range(11)]
        for t in tutors:
            assert send(p, t, "hi").status_code == 200
        assert DB.messages.count_documents({"from_user_id": p["id"], "cold": True}) == 0


# ---- Files: no token in URL ----
class TestFileTokenQuery:
    def test_query_token_rejected_header_ok(self):
        p = make_user("parent")
        up = requests.post(f"{BASE_URL}/api/uploads", files={"file": ("kid.png", io.BytesIO(PNG_BYTES), "image/png")},
                           headers=H(p), timeout=60)
        if up.status_code != 200:
            pytest.skip(f"upload failed {up.status_code} {up.text[:200]}")
        path = up.json()["path"]
        DB.parents.update_one({"user_id": p["id"]}, {"$set": {"children": [{"id": "c1", "name": "K", "age": 3, "avatar_url": path}]}}, upsert=True)
        r = requests.get(f"{BASE_URL}/api/files/{path}?token={p['tok']}", timeout=30)
        assert r.status_code in (401, 403), f"token-in-URL must not authenticate: {r.status_code}"
        r = requests.get(f"{BASE_URL}/api/files/{path}", headers=H(p), timeout=30)
        assert r.status_code == 200, r.text


# ---- CORS ----
class TestCORS:
    def _pre(self, origin):
        return requests.options(f"{BASE_URL}/api/tutors", headers={"Origin": origin, "Access-Control-Request-Method": "GET",
                                "Access-Control-Request-Headers": "authorization"}, timeout=30)

    def test_evil_origin_blocked(self):
        r = self._pre("https://evil.com")
        assert r.headers.get("access-control-allow-origin") is None, r.headers

    def test_preview_origin_allowed(self):
        r = self._pre(BASE_URL)
        assert r.headers.get("access-control-allow-origin") == BASE_URL, r.headers

    def test_evil_simple_get_no_acao_at_app(self):
        # NOTE: the preview ingress injects ACAO:* on simple GETs via the public URL (infra, not app),
        # so we assert the app's own behaviour on the backend origin.
        r = requests.get("http://localhost:8001/api/tutors", headers={"Origin": "https://evil.com"}, timeout=30)
        assert r.headers.get("access-control-allow-origin") is None
