# Seed / cleanup TEST_ accounts for session-11 block UI tests. Usage: python seed_session11_blocks_ui.py [seed|cleanup]
import json, os, sys, uuid
import requests

API = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/") + "/api"
OUT = "/tmp/blocks_ui_accounts.json"


def signup(role, label):
    email = f"test_{label}_{uuid.uuid4().hex[:6]}@example.com"
    r = requests.post(f"{API}/auth/signup", json={"email": email, "password": "password123", "name": f"TEST {label}", "role": role})
    r.raise_for_status()
    d = r.json()
    return {"email": email, "id": d["user"]["id"], "name": d["user"]["name"], "token": d["access_token"]}


def h(u):
    return {"Authorization": f"Bearer {u['token']}"}


def seed():
    p1 = signup("parent", "ParentOne")
    p2 = signup("parent", "ParentTwo")
    t1 = signup("tutor", "TutorChat")
    t2 = signup("tutor", "TutorProfile")
    t3 = signup("tutor", "TutorThree")
    for t in (t1, t2, t3):
        requests.patch(f"{API}/tutors/me/profile", headers=h(t), json={"bio": "TEST tutor bio", "languages": ["Spanish"], "hourly_rate_cents": 3000}).raise_for_status()
        t["tutor_id"] = requests.get(f"{API}/tutors/me/profile", headers=h(t)).json()["id"]
    for p in (p1, p2):
        requests.patch(f"{API}/parents/me/profile", headers=h(p), json={"city": "TEST Madrid"}).raise_for_status()
    requests.post(f"{API}/messages", headers=h(p1), json={"to_user_id": t1["id"], "text": "TEST hello tutor one"}).raise_for_status()
    requests.post(f"{API}/messages", headers=h(p2), json={"to_user_id": t3["id"], "text": "TEST hello tutor three"}).raise_for_status()
    data = {"p1": p1, "p2": p2, "t1": t1, "t2": t2, "t3": t3}
    json.dump(data, open(OUT, "w"), indent=1)
    print(json.dumps({k: {kk: v[kk] for kk in v if kk != "token"} for k, v in data.items()}, indent=1))


def cleanup():
    data = json.load(open(OUT))
    for k, u in data.items():
        print(k, requests.delete(f"{API}/auth/me", headers=h(u)).status_code)


if __name__ == "__main__":
    seed() if (sys.argv[1:] or ["seed"])[0] == "seed" else cleanup()
