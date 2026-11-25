"""Shared helpers for the integration suites — locate the backend and (optionally) restart it.

They locate the backend relative to this file and restart it with a command you configure, so they
work from wherever the repo is checked out.
"""
import os
import subprocess
import time
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values

BACKEND_DIR = Path(__file__).resolve().parents[1]
ENV_FILE = BACKEND_DIR / ".env"


def backend_env() -> dict:
    """backend/.env merged with the process environment (environment wins)."""
    env = {k: v for k, v in dotenv_values(ENV_FILE).items() if v is not None} if ENV_FILE.exists() else {}
    env.update({k: v for k, v in os.environ.items() if k in ("MONGO_URL", "DB_NAME", "EXPO_PUBLIC_BACKEND_URL")})
    return env


def backend_url() -> str:
    return (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_BACKEND_URL") or "http://localhost:8001").rstrip("/")


def mongo_db():
    from pymongo import MongoClient
    env = backend_env()
    return MongoClient(env.get("MONGO_URL", "mongodb://localhost:27017"))[env.get("DB_NAME", "babybabel")]


def backend_source() -> str:
    """All application source (not tests), for the static 'this guard is still in place' checks."""
    parts = []
    for p in sorted(BACKEND_DIR.rglob("*.py")):
        rel = p.relative_to(BACKEND_DIR).parts
        if rel[0] in ("tests", "tests_inprocess") or "__pycache__" in rel:
            continue
        parts.append(p.read_text(encoding="utf-8"))
    return "\n\n".join(parts)


def restart_backend(wait_seconds: int = 30) -> None:
    """Restart the API under test, e.g. to clear in-memory rate limits or reload .env.

    Set BACKEND_RESTART_CMD to whatever restarts your server (a systemd unit, a docker
    compose service, a supervisor program…). Without it, the calling test is skipped.
    """
    cmd = os.environ.get("BACKEND_RESTART_CMD")
    if not cmd:
        pytest.skip("needs BACKEND_RESTART_CMD to restart the API under test")
    subprocess.run(cmd, shell=True, check=False, capture_output=True)
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        time.sleep(1)
        try:
            if requests.get(f"{backend_url()}/api/", timeout=3).status_code == 200:
                return
        except requests.RequestException:
            pass
    pytest.fail("API didn't come back after restart")
