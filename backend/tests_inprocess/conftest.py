"""In-process tests: the real FastAPI app against an in-memory MongoDB (mongomock-motor).

No server, network or real database needed:  pytest tests_inprocess -n 0
"""
import os
import sys
import uuid
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
os.environ.update({
    "MONGO_URL": "mongodb://in-memory", "DB_NAME": f"test_{uuid.uuid4().hex[:8]}",
    "JWT_SECRET": "t" * 48, "SEED_TUTOR_PASSWORD": "password123",
    "DISABLE_BACKGROUND_WORKERS": "true", "PUSH_ENABLED": "false", "ENABLE_MOCK_CONFIRM": "true",
    "STRIPE_API_KEY": "", "EMERGENT_LLM_KEY": "",
})

import motor.motor_asyncio  # noqa: E402
from mongomock_motor import AsyncMongoMockClient  # noqa: E402

motor.motor_asyncio.AsyncIOMotorClient = AsyncMongoMockClient

import core  # noqa: E402
import server  # noqa: E402
from routes import auth as auth_routes, uploads as upload_routes  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

upload_routes._put_object_sync = lambda path, data, ctype: {"ok": True}  # no network
core._delete_object_sync = lambda path: True
auth_routes._delete_object_sync = lambda path: True

SENT_CODES: dict = {}


async def _capture_code(to, purpose, code):
    SENT_CODES[(to, purpose)] = code


auth_routes._email_code = _capture_code


@pytest.fixture(scope="session")
def client():
    with TestClient(server.app) as c:
        yield c


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    core._rate_buckets.clear()
    yield


@pytest.fixture
def codes():
    return SENT_CODES


def H(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture
def make_user(client):
    def _make(role: str = "parent", tz: str | None = None) -> dict:
        email = f"{role}-{uuid.uuid4().hex[:8]}@example.com"
        body = {"email": email, "password": "longenough1", "name": f"Test {role.title()}", "role": role}
        if tz:
            body["timezone"] = tz
        r = client.post("/api/auth/signup", json=body)
        assert r.status_code == 201, r.text
        return {"email": email, "token": r.json()["access_token"], "user": r.json()["user"], "h": H(r.json()["access_token"])}
    return _make


@pytest.fixture
def sofia(client):
    core._rate_buckets.clear()
    r = client.post("/api/auth/login", json={"email": "sofia@babybabel.dev", "password": "password123"})
    assert r.status_code == 200, r.text
    tok = r.json()["access_token"]
    profile = next(t for t in client.get("/api/tutors").json() if t["name"].startswith("Sof"))
    return {"token": tok, "h": H(tok), "user": r.json()["user"], "profile": profile}


@pytest.fixture
def db_call(client):
    """Run a database coroutine function on the app's event loop."""
    def _call(fn, *args, **kwargs):
        return client.portal.call(lambda: fn(*args, **kwargs))
    return _call
