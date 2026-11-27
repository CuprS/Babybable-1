# Session 12: directly exercises signup's paused-tombstone branch (unreachable via API because paused users get 423 on DELETE /auth/me)
import asyncio, hashlib, os, uuid, random
import requests
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv(__import__("pathlib").Path(__file__).resolve().parents[1] / ".env")
API = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_BACKEND_URL") or "http://localhost:8001").rstrip("/") + "/api"


def fp(email):
    local, _, domain = email.lower().strip().partition("@")
    return hashlib.sha256(f"{local.split('+', 1)[0]}@{domain}".encode()).hexdigest()


async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    tag = uuid.uuid4().hex[:8]
    email = f"test_tomb_{tag}@example.com"
    await db.account_tombstones.insert_one({"email_fp": fp(email), "suspended": True, "deleted_at": "2026-01-01T00:00:00+00:00"})
    try:
        r = requests.post(f"{API}/auth/signup", headers={"X-Forwarded-For": f"10.9.{random.randint(1,250)}.{random.randint(1,250)}"},
                          json={"email": f"TEST_Tomb_{tag}+re@example.com", "password": "password123", "name": "TEST_tomb", "role": "tutor", "accept_terms": True})
        print("signup status", r.status_code, r.text)
        u = await db.users.find_one({"email": f"test_tomb_{tag}+re@example.com"}, {"_id": 0, "password_hash": 0})
        print("user doc", u)
        t = await db.tutors.find_one({"user_id": u["id"]}) if u else None
        print("tutor profile created:", bool(t))
        l = requests.post(f"{API}/auth/login", headers={"X-Forwarded-For": "10.8.8.8"}, json={"email": f"test_tomb_{tag}+re@example.com", "password": "password123"})
        print("login status", l.status_code)
        if u:
            await db.users.delete_one({"id": u["id"]})
    finally:
        await db.account_tombstones.delete_one({"email_fp": fp(email)})

asyncio.run(main())
