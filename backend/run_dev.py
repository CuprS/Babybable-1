"""Run the API locally with safe development defaults:   python run_dev.py

- Database: a local file-backed stand-in (data/dev-db.json), so you don't need MongoDB.
- Uploads: stored in data/uploads.  Email: not sent; codes are printed in this window.
- Admin login: admin@example.com / admin-pass-123. The database starts empty; set
  SEED_SAMPLE_TUTORS=true to add two verified sample tutors (password123).
- Reloads automatically when you edit backend code. Listens on http://127.0.0.1:8001 only.

Anything you put in backend/.env (or the environment) overrides these defaults — e.g. set
MONGO_URL to a real MongoDB to use one.
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.chdir(HERE)
sys.path.insert(0, str(HERE))
# Windows consoles default to a legacy code page; use UTF-8 here and in the reload worker.
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

try:
    from dotenv import load_dotenv
except ImportError:
    sys.exit("Install the dev dependencies first:  pip install -r requirements-dev.txt")

load_dotenv(HERE / ".env")  # your own settings win over the defaults below

DEV_DEFAULTS = {
    "MONGO_URL": "memory://data/dev-db.json",
    "DB_NAME": "babybabel_dev",
    "JWT_SECRET": "local-development-only-secret-do-not-use-in-production",
    "SEED_TUTOR_PASSWORD": "password123",
    "ADMIN_EMAIL": "admin@example.com",
    "ADMIN_INITIAL_PASSWORD": "admin-pass-123",
    "DEV_LOG_EMAIL_CODES": "true",
    "PUSH_ENABLED": "false",
    "STORAGE_BACKEND": "local",
    "PUBLIC_WEB_URL": "http://localhost:8081",
    "ENABLE_MOCK_CONFIRM": "true",
}
for key, value in DEV_DEFAULTS.items():
    os.environ.setdefault(key, value)

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8001"))
    print(f"\n  Babybabel API (development) - http://127.0.0.1:{port}/api/\n")
    uvicorn.run("server:app", host="127.0.0.1", port=port, reload=True, reload_dirs=[str(HERE)])
