# Session 11: user blocking (POST /api/blocks, status, admin list, enforcement across tutors/messages/bookings/parents)
import os
import uuid
import pytest
import requests

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ["EXPO_BACKEND_URL"]).rstrip("/")
API = f"{BASE_URL}/api"
ADMIN = ("copperstone17@gmail.com", "REDACTED-PASSWORD")


def _signup(role, label):
    email = f"test_{label}_{uuid.uuid4().hex[:8]}@example.com"
    r = requests.post(f"{API}/auth/signup", json={"email": email, "password": "password123", "name": f"TEST_{label}", "role": role})
    if r.status_code == 429:
        pytest.skip("auth rate limited")
    assert r.status_code == 201, r.text
    d = r.json()
    return {"token": d["access_token"], "id": d["user"]["id"], "name": d["user"]["name"], "h": {"Authorization": f"Bearer {d['access_token']}"}}


@pytest.fixture(scope="module")
def users():
    pa = _signup("parent", "blkparentA")
    ta = _signup("tutor", "blktutorA")
    tb = _signup("tutor", "blktutorB")
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN[0], "password": ADMIN[1]})
    assert r.status_code == 200, r.text
    adm = {"id": r.json()["user"]["id"], "h": {"Authorization": f"Bearer {r.json()['access_token']}"}}
    # tutor A profile so it shows in search
    requests.patch(f"{API}/tutors/me/profile", headers=ta["h"], json={"bio": "TEST_ block tutor", "languages": ["Spanish"], "hourly_rate_cents": 3000})
    ta["tutor_id"] = requests.get(f"{API}/tutors/me/profile", headers=ta["h"]).json()["id"]
    rp = requests.patch(f"{API}/parents/me/profile", headers=pa["h"], json={"city": "TEST_ Madrid"})
    assert rp.status_code == 200, rp.text
    # relationship: parent writes first, tutor replies + invites
    assert requests.post(f"{API}/messages", headers=pa["h"], json={"to_user_id": ta["id"], "text": "TEST_ hi"}).status_code == 200
    assert requests.post(f"{API}/messages", headers=ta["h"], json={"to_user_id": pa["id"], "text": "TEST_ hello"}).status_code == 200
    inv = requests.post(f"{API}/messages/invitation", headers=ta["h"], json={"to_user_id": pa["id"], "price_cents": 3000, "date": "2027-03-03", "time": "10:00", "duration_minutes": 60, "language": "Spanish"})
    ta["invitation_id"] = inv.json().get("id") if inv.status_code == 200 else None
    yield {"pa": pa, "ta": ta, "tb": tb, "admin": adm}
    for u in (pa, ta, tb):
        requests.delete(f"{API}/auth/me", headers=u["h"])


class TestBlocks:
    def test_pre_block_visibility(self, users):
        pa, ta = users["pa"], users["ta"]
        ids = [t["id"] for t in requests.get(f"{API}/tutors", headers=pa["h"]).json()]
        assert ta["tutor_id"] in ids
        assert requests.get(f"{API}/tutors/{ta['tutor_id']}", headers=pa["h"]).status_code == 200
        assert requests.get(f"{API}/parents/{pa['id']}/public", headers=ta["h"]).status_code == 200
        assert ta["invitation_id"], "invitation setup failed"

    def test_validation(self, users):
        pa, ta = users["pa"], users["ta"]
        r = requests.post(f"{API}/blocks", headers=pa["h"], json={"user_id": ta["id"], "reason": "other", "details": "short"})
        assert r.status_code == 422
        assert requests.post(f"{API}/blocks", headers=pa["h"], json={"user_id": pa["id"], "reason": "spam"}).status_code == 400
        assert requests.post(f"{API}/blocks", headers=pa["h"], json={"user_id": users["admin"]["id"], "reason": "spam"}).status_code == 400
        assert requests.post(f"{API}/blocks", headers=pa["h"], json={"user_id": "nope", "reason": "spam"}).status_code == 404
        assert requests.post(f"{API}/blocks", headers=pa["h"], json={"user_id": ta["id"], "reason": "badreason"}).status_code == 422
        assert requests.post(f"{API}/blocks", json={"user_id": ta["id"], "reason": "spam"}).status_code == 401
        # still not blocked
        assert requests.get(f"{API}/blocks/status/{ta['id']}", headers=pa["h"]).json() == {"blocked": False}

    def test_block_and_duplicate(self, users):
        pa, ta = users["pa"], users["ta"]
        r = requests.post(f"{API}/blocks", headers=pa["h"], json={"user_id": ta["id"], "reason": "harassment", "details": "TEST_ rude messages"})
        assert r.status_code == 200 and r.json() == {"ok": True}
        assert requests.post(f"{API}/blocks", headers=pa["h"], json={"user_id": ta["id"], "reason": "spam"}).status_code == 409

    def test_status_both_ways(self, users):
        pa, ta, tb = users["pa"], users["ta"], users["tb"]
        assert requests.get(f"{API}/blocks/status/{ta['id']}", headers=pa["h"]).json()["blocked"] is True
        assert requests.get(f"{API}/blocks/status/{pa['id']}", headers=ta["h"]).json()["blocked"] is True
        assert requests.get(f"{API}/blocks/status/{pa['id']}", headers=tb["h"]).json()["blocked"] is False

    def test_parent_side_hidden(self, users):
        pa, ta = users["pa"], users["ta"]
        ids = [t["id"] for t in requests.get(f"{API}/tutors", headers=pa["h"]).json()]
        assert ta["tutor_id"] not in ids
        assert ta["tutor_id"] not in [t["id"] for t in requests.get(f"{API}/tutors/map", headers=pa["h"]).json()]
        assert requests.get(f"{API}/tutors/{ta['tutor_id']}", headers=pa["h"]).status_code == 404
        assert requests.get(f"{API}/tutors/by-user/{ta['id']}", headers=pa["h"]).status_code == 404
        assert ta["id"] not in [t["other_user_id"] for t in requests.get(f"{API}/messages/threads", headers=pa["h"]).json()]
        assert requests.get(f"{API}/messages/thread/{ta['id']}", headers=pa["h"]).json() == []

    def test_tutor_side_hidden(self, users):
        pa, ta = users["pa"], users["ta"]
        assert requests.get(f"{API}/parents/{pa['id']}/public", headers=ta["h"]).status_code == 404
        assert pa["id"] not in [t["other_user_id"] for t in requests.get(f"{API}/messages/threads", headers=ta["h"]).json()]
        assert requests.get(f"{API}/messages/thread/{pa['id']}", headers=ta["h"]).json() == []

    def test_unrelated_tutor_still_visible(self, users):
        ids = [t["id"] for t in requests.get(f"{API}/tutors").json()]
        assert users["ta"]["tutor_id"] in ids  # anonymous browsing unaffected

    def test_messaging_blocked_both_ways(self, users):
        pa, ta = users["pa"], users["ta"]
        r1 = requests.post(f"{API}/messages", headers=pa["h"], json={"to_user_id": ta["id"], "text": "TEST_ x"})
        r2 = requests.post(f"{API}/messages", headers=ta["h"], json={"to_user_id": pa["id"], "text": "TEST_ x"})
        assert r1.status_code == 403 and r2.status_code == 403
        assert "no longer contact" in r1.json()["detail"]
        r3 = requests.post(f"{API}/messages/invitation", headers=ta["h"], json={"to_user_id": pa["id"], "price_cents": 3000, "date": "2027-03-04", "time": "10:00", "duration_minutes": 60, "language": "Spanish"})
        assert r3.status_code == 403

    def test_invitation_accept_and_booking_blocked(self, users):
        pa, ta = users["pa"], users["ta"]
        if ta["invitation_id"]:
            r = requests.post(f"{API}/messages/invitation/{ta['invitation_id']}/accept", headers=pa["h"])
            assert r.status_code == 403, r.text
        r = requests.post(f"{API}/bookings", headers=pa["h"], json={"tutor_id": ta["tutor_id"], "date": "2027-03-05", "time": "10:00", "duration_minutes": 60, "language": "Spanish"})
        assert r.status_code == 404, r.text

    def test_admin_list(self, users):
        pa, ta = users["pa"], users["ta"]
        assert requests.get(f"{API}/admin/blocks", headers=pa["h"]).status_code == 403
        rows = requests.get(f"{API}/admin/blocks", headers=users["admin"]["h"]).json()
        mine = [b for b in rows if b["blocker_id"] == pa["id"] and b["blocked_id"] == ta["id"]]
        assert len(mine) == 1
        b = mine[0]
        assert b["reason"] == "harassment" and b["details"] == "TEST_ rude messages"
        assert b["blocker"]["name"] == pa["name"] and b["blocked"]["name"] == ta["name"]
        assert b["times_blocked"] >= 1 and "_id" not in b

    def test_admin_still_sees_parent(self, users):
        r = requests.get(f"{API}/parents/{users['pa']['id']}/public", headers=users["admin"]["h"])
        assert r.status_code == 200  # admin bypasses block

    def test_cascade_on_delete(self, users):
        tb, pa = users["tb"], users["pa"]
        # tutor B blocks parent, then deletes account -> block row gone from admin list
        assert requests.post(f"{API}/blocks", headers=tb["h"], json={"user_id": pa["id"], "reason": "other", "details": "TEST_ long enough details"}).status_code == 200
        assert requests.delete(f"{API}/auth/me", headers=tb["h"]).status_code == 200
        rows = requests.get(f"{API}/admin/blocks", headers=users["admin"]["h"]).json()
        assert not [b for b in rows if b["blocker_id"] == tb["id"]]
