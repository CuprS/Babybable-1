# Seeds TEST_ users for session10 UI checks (privacy locked screen + cold-cap chat toast). Writes /tmp/s10_ui.json
import json, uuid
from datetime import datetime, timezone
import sys
sys.path.insert(0, "/app/backend/tests")
from test_babybabel_session10_privacy_spam import make_user, DB

owner = make_user("parent", with_profile=True)
DB.parents.update_one({"user_id": owner["id"]}, {"$set": {"languages_desired": ["Spanish"], "hours_per_week": 4}})
unrelated = make_user("tutor")
related = make_user("tutor")
DB.messages.insert_one({"id": str(uuid.uuid4()), "from_user_id": owner["id"], "to_user_id": related["id"], "text": "Hi!",
                        "kind": "text", "invitation": None, "created_at": datetime.now(timezone.utc).isoformat(), "cold": False})
capped = make_user("tutor")
now = datetime.now(timezone.utc).isoformat()
for _ in range(10):
    DB.messages.insert_one({"id": str(uuid.uuid4()), "from_user_id": capped["id"], "to_user_id": str(uuid.uuid4()), "text": "cold",
                            "kind": "text", "invitation": None, "created_at": now, "cold": True})
target = make_user("parent", with_profile=True)
json.dump({"owner": owner, "unrelated": unrelated, "related": related, "capped": capped, "target": target}, open("/tmp/s10_ui.json", "w"))
print(json.dumps({k: v["id"] for k, v in {"owner": owner, "unrelated": unrelated, "related": related, "capped": capped, "target": target}.items()}))
