# Session 12 UI cleanup: reinstate + delete the TEST_ users created by seed_session12_safety_ui.py (by id/token from seed json files)
import json, os, sys, random
import requests

API = os.environ["EXPO_BACKEND_URL"].rstrip("/") + "/api"
r = requests.post(f"{API}/auth/login", headers={"X-Forwarded-For": "10.6.6.6"}, json={"email": "copperstone17@gmail.com", "password": "REDACTED-PASSWORD"})
ah = {"Authorization": f"Bearer {r.json()['access_token']}"}
for path in sys.argv[1:]:
    d = json.load(open(path))
    for u in d["blockers"] + [d["P"], d["Q"]]:  # blockers first so their blocks vanish (no tombstones)
        requests.post(f"{API}/admin/users/{u['id']}/reinstate", headers=ah)
        x = requests.delete(f"{API}/auth/me", headers={"Authorization": f"Bearer {u['token']}"})
        print(u["email"], x.status_code)
left = [x["email"] for x in requests.get(f"{API}/admin/suspended", headers=ah).json()]
print("still paused:", left)
print("alert email:", requests.get(f"{API}/admin/settings/safety-email", headers=ah).json())
