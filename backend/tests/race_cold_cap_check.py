# Concurrency probe: can a fresh tutor exceed the 10 cold-message/day cap with parallel requests?
import sys
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent))
from test_babybabel_session10_privacy_spam import make_user, send, DB, CREATED_USERS

t = make_user("tutor")
parents = [make_user("parent") for _ in range(20)]
with ThreadPoolExecutor(max_workers=20) as ex:
    codes = list(ex.map(lambda p: send(t, p, "parallel hi").status_code, parents))
print("status codes:", sorted(codes))
print("cold msgs stored:", DB.messages.count_documents({"from_user_id": t["id"], "cold": True}))
for uid in CREATED_USERS:
    DB.messages.delete_many({"$or": [{"from_user_id": uid}, {"to_user_id": uid}]})
    DB.tutors.delete_many({"user_id": uid}); DB.users.delete_many({"id": uid})
