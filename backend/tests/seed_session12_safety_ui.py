# Session 12 UI seed: creates TEST_ users — P (already paused, 3 blockers) and Q (active, 2 blockers + 1 spare blocker token)
import json, os, random, uuid
import requests

API = os.environ["EXPO_BACKEND_URL"].rstrip("/") + "/api"


def ip():
    return {"X-Forwarded-For": f"10.7.{random.randint(1,250)}.{random.randint(1,250)}"}


def signup(role, label):
    email = f"test_{label}_{uuid.uuid4().hex[:8]}@example.com"
    r = requests.post(f"{API}/auth/signup", headers=ip(), json={"email": email, "password": "password123", "name": f"TEST_{label}", "role": role})
    r.raise_for_status()
    d = r.json()
    return {"email": email, "id": d["user"]["id"], "token": d["access_token"]}


def block(b, tid):
    r = requests.post(f"{API}/blocks", headers={"Authorization": f"Bearer {b['token']}"}, json={"user_id": tid, "reason": "spam"})
    r.raise_for_status()


p = signup("parent", "uiP")
q = signup("parent", "uiQ")
bl = [signup("tutor", f"uiB{i}") for i in range(3)]
for b in bl:
    block(b, p["id"])
block(bl[0], q["id"])
block(bl[1], q["id"])
print(json.dumps({"P": p, "Q": q, "blockers": bl}))
