"""Integration tests: they call a RUNNING backend over HTTP and seed/inspect its MongoDB directly.

They create and delete real accounts, so they default to a local server and refuse to run
against a remote one unless you explicitly opt in with ALLOW_REMOTE_TESTS=1.

    uvicorn server:app --port 8001            # with SEED_TUTOR_PASSWORD=password123
    EXPO_PUBLIC_BACKEND_URL=http://localhost:8001 pytest tests

For fast checks that need no server or database, use tests_inprocess/ instead.
"""
import os
from urllib.parse import urlparse

import pytest
import requests

BASE = os.environ.get("EXPO_PUBLIC_BACKEND_URL") or "http://localhost:8001"
BASE_URL = BASE.rstrip("/")
_host = urlparse(BASE_URL).hostname or ""
if _host not in ("localhost", "127.0.0.1", "backend") and os.environ.get("ALLOW_REMOTE_TESTS") != "1":
    pytest.exit(
        f"Refusing to run integration tests against {BASE_URL} — they create and delete real data. "
        "Point EXPO_PUBLIC_BACKEND_URL at a local/test server, or set ALLOW_REMOTE_TESTS=1 if you're sure.",
        returncode=2,
    )


@pytest.fixture(scope="session")
def base_url():
    return BASE_URL


@pytest.fixture
def api_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s
