# Session 12 UI cleanup: reinstate + delete the TEST_ users created by seed_session12_safety_ui.py (by id/token from seed json files)
import json, os, sys, random
import requests
from _support import admin_session  # noqa: E402

API = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_BACKEND_URL") or "http://localhost:8001").rstrip("/") + "/api"
ah = {"Authorization": f"Bearer {admin_session()['access_token']}"}
for path in sys.argv[1:]:
    d = json.load(open(path))
    for u in d["blockers"] + [d["P"], d["Q"]]:  # blockers first so their blocks vanish (no tombstones)
        requests.post(f"{API}/admin/users/{u['id']}/reinstate", headers=ah)
        x = requests.delete(f"{API}/auth/me", headers={"Authorization": f"Bearer {u['token']}"})
        print(u["email"], x.status_code)
left = [x["email"] for x in requests.get(f"{API}/admin/suspended", headers=ah).json()]
print("still paused:", left)
print("alert email:", requests.get(f"{API}/admin/settings/safety-email", headers=ah).json())
