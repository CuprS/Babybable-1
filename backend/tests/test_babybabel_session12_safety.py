# Session 12: safety automation — auto-pause at 3 distinct blockers, 423 handling, admin paused list/reinstate,
# safety alert email setting, safety-reason email send, block-evasion guard (delete + re-signup with same email fp)
import os
import time
import uuid
import random
import pytest
import requests

BASE_URL = (os.environ.get("EXPO_BACKEND_URL") or os.environ["EXPO_PUBLIC_BACKEND_URL"]).rstrip("/")
API = f"{BASE_URL}/api"
ADMIN = ("copperstone17@gmail.com", "REDACTED-PASSWORD")
LOG = "/var/log/supervisor/backend.err.log"
TEST_ALERT = "delivered@resend.dev"


def _ip():
    # unique client ip per auth call (only honoured when hitting backend directly) to stay under rate limits
    return {"X-Forwarded-For": f"10.{random.randint(1,250)}.{random.randint(1,250)}.{random.randint(1,250)}"}


def _signup(role, label, email=None, expect=201):
    email = email or f"test_{label}_{uuid.uuid4().hex[:8]}@example.com"
    USED_EMAILS.append(email)
    r = requests.post(f"{API}/auth/signup", headers=_ip(), json={"email": email, "password": "password123", "name": f"TEST_{label}", "role": role})
    if r.status_code == 429:
        pytest.skip("auth rate limited")
    assert r.status_code == expect, r.text
    if expect != 201:
        return r
    d = r.json()
    return {"email": email, "id": d["user"]["id"], "h": {"Authorization": f"Bearer {d['access_token']}"}}


def _login(email, pw="password123"):
    return requests.post(f"{API}/auth/login", headers=_ip(), json={"email": email, "password": pw})


def _block(u, target_id, reason="spam", details=""):
    return requests.post(f"{API}/blocks", headers=u["h"], json={"user_id": target_id, "reason": reason, "details": details})


def _email_log_count():
    try:
        with open(LOG) as f:
            return sum(1 for line in f if "api/v1/email/send" in line and "202 Accepted" in line)
    except FileNotFoundError:
        return -1


@pytest.fixture(scope="module")
def admin():
    r = _login(*ADMIN)
    assert r.status_code == 200, r.text
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    orig = requests.get(f"{API}/admin/settings/safety-email", headers=h).json().get("email")
    yield {"h": h, "orig": orig}
    # restore alert email to the owner's address
    requests.put(f"{API}/admin/settings/safety-email", headers=h, json={"email": "copperstone17@gmail.com"})


CREATED = []
USED_EMAILS = []


def _fp(email):
    import hashlib
    local, _, domain = email.lower().strip().partition("@")
    local = local.split("+", 1)[0]
    if domain in ("gmail.com", "googlemail.com"):
        local, domain = local.replace(".", ""), "gmail.com"
    return hashlib.sha256(f"{local}@{domain}".encode()).hexdigest()


@pytest.fixture(scope="module", autouse=True)
def cleanup(admin):
    yield
    for u in CREATED:
        requests.post(f"{API}/admin/users/{u['id']}/reinstate", headers=admin["h"])
        requests.delete(f"{API}/auth/me", headers=u["h"])
    # remove leftover blocks/tombstones keyed on the TEST_ email fingerprints used by this run
    fps = list({_fp(e) for e in USED_EMAILS})
    for row in requests.get(f"{API}/admin/suspended", headers=admin["h"]).json():  # paused re-signups (no token)
        if _fp(row["email"]) in fps:
            requests.post(f"{API}/admin/users/{row['id']}/reinstate", headers=admin["h"])
            lr = _login(row["email"])
            if lr.status_code == 200:
                requests.delete(f"{API}/auth/me", headers={"Authorization": f"Bearer {lr.json()['access_token']}"})
    d = _db()
    d.blocks.delete_many({"blocked_email_fp": {"$in": fps}})
    d.account_tombstones.delete_many({"email_fp": {"$in": fps}})


def _mk(role, label, **kw):
    u = _signup(role, label, **kw)
    if isinstance(u, dict):
        CREATED.append(u)
    return u


# ---- Safety alert email setting ----
class TestSafetyEmailSetting:
    def test_get_admin_only(self, admin):
        r = requests.get(f"{API}/admin/settings/safety-email", headers=admin["h"])
        assert r.status_code == 200 and "@" in r.json()["email"]
        p = _mk("parent", "s12nonadmin")
        assert requests.get(f"{API}/admin/settings/safety-email", headers=p["h"]).status_code == 403
        assert requests.put(f"{API}/admin/settings/safety-email", headers=p["h"], json={"email": "x@y.com"}).status_code == 403
        assert requests.get(f"{API}/admin/settings/safety-email").status_code == 401

    def test_put_invalid_422(self, admin):
        for bad in ["notanemail", "", "a@", "@b.com"]:
            r = requests.put(f"{API}/admin/settings/safety-email", headers=admin["h"], json={"email": bad})
            assert r.status_code == 422, (bad, r.status_code)

    def test_put_persists_lowercased(self, admin):
        r = requests.put(f"{API}/admin/settings/safety-email", headers=admin["h"], json={"email": "Delivered@Resend.dev"})
        assert r.status_code == 200 and r.json()["email"] == TEST_ALERT
        assert requests.get(f"{API}/admin/settings/safety-email", headers=admin["h"]).json()["email"] == TEST_ALERT


# ---- Auto-pause at 3 distinct blockers + reinstate ----
class TestAutoPause:
    state = {}

    def test_setup_and_two_blocks_still_active(self, admin):
        t = _mk("tutor", "s12target")
        requests.patch(f"{API}/tutors/me/profile", headers=t["h"], json={"bio": "TEST_ s12 pause", "languages": ["Spanish"], "hourly_rate_cents": 3000})
        t["tutor_id"] = requests.get(f"{API}/tutors/me/profile", headers=t["h"]).json()["id"]
        bs = [_mk("parent", f"s12b{i}") for i in range(3)]
        self.state.update(t=t, bs=bs)
        assert _block(bs[0], t["id"], "spam").status_code == 200
        assert _block(bs[1], t["id"], "harassment").status_code == 200
        assert _block(bs[1], t["id"], "spam").status_code == 409  # same person twice doesn't count
        assert requests.get(f"{API}/auth/me", headers=t["h"]).status_code == 200
        ids = [x["id"] for x in requests.get(f"{API}/tutors").json()]
        assert t["tutor_id"] in ids

    def test_third_distinct_block_pauses(self, admin):
        t, bs = self.state["t"], self.state["bs"]
        before = _email_log_count()
        assert _block(bs[2], t["id"], "fake").status_code == 200
        r = requests.get(f"{API}/auth/me", headers=t["h"])
        assert r.status_code == 423 and "paused" in r.json()["detail"].lower()
        assert requests.get(f"{API}/notifications", headers=t["h"]).status_code == 423
        assert _login(t["email"]).status_code == 423
        assert _login(t["email"], "wrongpass").status_code == 401  # no paused-state leak with wrong password
        time.sleep(4)
        assert _email_log_count() > before, "pause should email admin"

    def test_paused_hidden_from_search_map_detail(self):
        t = self.state["t"]
        assert t["tutor_id"] not in [x["id"] for x in requests.get(f"{API}/tutors").json()]
        assert t["tutor_id"] not in [x["id"] for x in requests.get(f"{API}/tutors", params={"q": "TEST_ s12 pause"}).json()]
        m = requests.get(f"{API}/tutors/map")
        assert m.status_code == 200 and t["tutor_id"] not in str(m.json())
        assert requests.get(f"{API}/tutors/{t['tutor_id']}").status_code == 404

    def test_admin_lists_paused(self, admin):
        r = requests.get(f"{API}/admin/suspended", headers=admin["h"])
        assert r.status_code == 200
        row = next((x for x in r.json() if x["id"] == self.state["t"]["id"]), None)
        assert row and row["blocked_by"] == 3 and "_id" not in row and "password_hash" not in row
        assert "3" in row["suspended_reason"]
        assert requests.get(f"{API}/admin/suspended", headers=self.state["bs"][0]["h"]).status_code == 403

    def test_reinstate_restores(self, admin):
        t = self.state["t"]
        assert requests.post(f"{API}/admin/users/{t['id']}/reinstate", headers=self.state["bs"][0]["h"]).status_code == 403
        r = requests.post(f"{API}/admin/users/{t['id']}/reinstate", headers=admin["h"])
        assert r.status_code == 200 and r.json()["ok"] is True
        assert requests.post(f"{API}/admin/users/{t['id']}/reinstate", headers=admin["h"]).status_code == 404
        assert requests.get(f"{API}/auth/me", headers=t["h"]).status_code == 200
        assert _login(t["email"]).status_code == 200
        assert requests.get(f"{API}/tutors/{t['tutor_id']}").status_code == 200
        assert t["tutor_id"] in [x["id"] for x in requests.get(f"{API}/tutors").json()]
        assert t["id"] not in [x["id"] for x in requests.get(f"{API}/admin/suspended", headers=admin["h"]).json()]

    def test_new_blocks_needed_after_reinstate(self, admin):
        t = self.state["t"]
        nb = [_mk("parent", f"s12n{i}") for i in range(3)]
        assert _block(nb[0], t["id"], "spam").status_code == 200  # 4th total
        assert requests.get(f"{API}/auth/me", headers=t["h"]).status_code == 200
        assert _block(nb[1], t["id"], "spam").status_code == 200  # 5th total, 2 new
        assert requests.get(f"{API}/auth/me", headers=t["h"]).status_code == 200
        assert _block(nb[2], t["id"], "spam").status_code == 200  # 3 new -> paused again
        assert requests.get(f"{API}/auth/me", headers=t["h"]).status_code == 423
        assert requests.post(f"{API}/admin/users/{t['id']}/reinstate", headers=admin["h"]).status_code == 200

    def test_admin_never_paused(self, admin):
        me = requests.get(f"{API}/auth/me", headers=admin["h"]).json()
        p = _mk("parent", "s12adm")
        assert _block(p, me["id"], "spam").status_code == 400


# ---- Safety-reason block email ----
class TestSafetyEmailSend:
    def test_non_safety_block_no_email(self):
        a, b = _mk("parent", "s12ns_a"), _mk("tutor", "s12ns_b")
        before = _email_log_count()
        assert _block(a, b["id"], "spam").status_code == 200
        time.sleep(3)
        assert _email_log_count() == before

    def test_safety_block_sends_email(self, admin):
        assert requests.get(f"{API}/admin/settings/safety-email", headers=admin["h"]).json()["email"] == TEST_ALERT
        a, b = _mk("parent", "s12sf_a"), _mk("tutor", "s12sf_b")
        before = _email_log_count()
        assert _block(a, b["id"], "safety", "TEST_ automated safety check <b>x</b>").status_code == 200
        time.sleep(5)
        assert _email_log_count() == before + 1


# ---- Block-evasion guard ----
class TestEvasion:
    state = {}

    def test_block_survives_delete_and_resignup_alias_case(self):
        tutor = _mk("tutor", "s12ev_t")
        tag = uuid.uuid4().hex[:8]
        email = f"test_evade_{tag}@example.com"
        x = _signup("parent", "s12ev_x", email=email)
        assert _block(tutor, x["id"], "harassment").status_code == 200
        assert requests.delete(f"{API}/auth/me", headers=x["h"]).status_code == 200
        x2 = _mk("parent", "s12ev_x2", email=f"TEST_Evade_{tag}+again@Example.com")
        assert x2["id"] != x["id"]
        assert requests.get(f"{API}/blocks/status/{tutor['id']}", headers=x2["h"]).json()["blocked"] is True
        r = requests.post(f"{API}/messages", headers=x2["h"], json={"to_user_id": tutor["id"], "text": "TEST_ hi again"})
        assert r.status_code == 403, r.text
        self.state.update(tutor=tutor, x2=x2, tag=tag)

    def test_second_alias_does_not_unblock_first(self):
        # creating yet another alias account must not move the block off the existing alias account
        tutor, x2, tag = self.state["tutor"], self.state["x2"], self.state["tag"]
        x3 = _mk("parent", "s12ev_x3", email=f"test_evade_{tag}+third@example.com")
        s2 = requests.get(f"{API}/blocks/status/{tutor['id']}", headers=x2["h"]).json()["blocked"]
        s3 = requests.get(f"{API}/blocks/status/{tutor['id']}", headers=x3["h"]).json()["blocked"]
        assert s2 is True, f"alias #1 got unblocked when alias #2 signed up (x2={s2}, x3={s3})"
        assert s3 is True, f"alias #2 not blocked (x2={s2}, x3={s3})"

    def test_live_alias_without_delete_blocked(self):
        # X blocked, X NOT deleted -> x+1 signs up -> blocked; X stays blocked
        tutor = _mk("tutor", "s12live_t")
        tag = uuid.uuid4().hex[:8]
        x = _mk("parent", "s12live_x", email=f"test_live_{tag}@example.com")
        assert _block(tutor, x["id"], "spam").status_code == 200
        x1 = _mk("parent", "s12live_x1", email=f"test_live_{tag}+1@example.com")
        assert requests.get(f"{API}/blocks/status/{tutor['id']}", headers=x1["h"]).json()["blocked"] is True
        assert requests.get(f"{API}/blocks/status/{tutor['id']}", headers=x["h"]).json()["blocked"] is True
        assert requests.post(f"{API}/messages", headers=x1["h"], json={"to_user_id": tutor["id"], "text": "TEST_ hi"}).status_code == 403

    def test_gmail_dot_variant_blocked(self):
        tutor = _mk("tutor", "s12dot_t")
        tag = uuid.uuid4().hex[:6]
        x = _mk("parent", "s12dot_x", email=f"testdot{tag}ab@gmail.com")
        assert _block(tutor, x["id"], "harassment").status_code == 200
        x2 = _mk("parent", "s12dot_x2", email=f"test.dot{tag}.a.b@googlemail.com")
        assert requests.get(f"{API}/blocks/status/{tutor['id']}", headers=x2["h"]).json()["blocked"] is True
        # non-gmail dots are NOT stripped
        x3 = _mk("parent", "s12dot_x3", email=f"test.dot{tag}.a.b@example.com")
        assert requests.get(f"{API}/blocks/status/{tutor['id']}", headers=x3["h"]).json()["blocked"] is False

    def test_paused_user_delete_then_resignup_423(self):
        tag = uuid.uuid4().hex[:8]
        email = f"test_pz_{tag}@example.com"
        p = _signup("parent", "s12pz", email=email)
        CREATED.append(p)
        bl = [_mk("tutor", f"s12pzb{i}") for i in range(3)]
        for b in bl:
            assert _block(b, p["id"], "spam").status_code == 200
        assert requests.get(f"{API}/auth/me", headers=p["h"]).status_code == 423
        d = requests.delete(f"{API}/auth/me", headers=p["h"])
        assert d.status_code == 200, f"paused user can't delete their account: {d.status_code} {d.text}"
        CREATED.remove(p)
        r = _signup("parent", "s12pz2", email=f"test_pz_{tag}+x@example.com", expect=423)
        assert "paused" in r.json()["detail"].lower()
        assert _login(f"test_pz_{tag}+x@example.com").status_code == 423
        # re-attempting the same email again -> generic 400 (account exists, paused)
        _signup("parent", "s12pz3", email=f"test_pz_{tag}+x@example.com", expect=400)

    def test_paused_tutor_delete_resignup_profile_hidden(self, admin):
        tag = uuid.uuid4().hex[:8]
        email = f"test_pzt_{tag}@example.com"
        t = _signup("tutor", "s12pzt", email=email)
        bl = [_mk("parent", f"s12pztb{i}") for i in range(3)]
        for b in bl:
            assert _block(b, t["id"], "spam").status_code == 200
        assert requests.delete(f"{API}/auth/me", headers=t["h"]).status_code == 200
        _signup("tutor", "s12pzt2", email=f"TEST_PZT_{tag}+re@example.com", expect=423)
        row = next((x for x in requests.get(f"{API}/admin/suspended", headers=admin["h"]).json()
                    if x["email"] == f"test_pzt_{tag}+re@example.com"), None)
        assert row and row["role"] == "tutor", row
        tid = _db().tutors.find_one({"user_id": row["id"]}, {"_id": 0})
        assert tid and tid.get("suspended") is True, tid
        assert tid["id"] not in [x["id"] for x in requests.get(f"{API}/tutors").json()]
        assert requests.get(f"{API}/tutors/{tid['id']}").status_code == 404
        # reinstate -> profile becomes visible, then clean up
        assert requests.post(f"{API}/admin/users/{row['id']}/reinstate", headers=admin["h"]).status_code == 200
        assert requests.get(f"{API}/tutors/{tid['id']}").status_code == 200
        lr = _login(f"test_pzt_{tag}+re@example.com")
        assert lr.status_code == 200
        requests.delete(f"{API}/auth/me", headers={"Authorization": f"Bearer {lr.json()['access_token']}"})


# ---- Probes for remaining evasion paths (expected to be guarded) ----
class TestEvasionProbes:
    def test_alias_of_live_paused_account_is_paused(self):
        # X paused (3 blockers), X NOT deleted, signs up x+alt -> should not get a clean account
        tag = uuid.uuid4().hex[:8]
        x = _mk("parent", "s12lp", email=f"test_lp_{tag}@example.com")
        for i in range(3):
            assert _block(_mk("tutor", f"s12lpb{i}"), x["id"], "spam").status_code == 200
        assert requests.get(f"{API}/auth/me", headers=x["h"]).status_code == 423
        r = requests.post(f"{API}/auth/signup", headers=_ip(), json={"email": f"test_lp_{tag}+alt@example.com", "password": "password123", "name": "TEST_s12lp2", "role": "parent"})
        if r.status_code == 201:
            CREATED.append({"id": r.json()["user"]["id"], "h": {"Authorization": f"Bearer {r.json()['access_token']}"}})
        assert r.status_code == 423, f"alias of a live paused account got an active account: {r.status_code}"

    def test_tombstone_not_downgraded_by_other_alias_delete(self):
        # live alias Y exists before X is paused; X paused+deleted; then Y deleted -> tombstone must stay suspended
        tag = uuid.uuid4().hex[:8]
        tutor0 = _mk("tutor", "s12tb_t0")
        x = _signup("parent", "s12tb_x", email=f"test_tb_{tag}@example.com")
        assert _block(tutor0, x["id"], "spam").status_code == 200
        y = _signup("parent", "s12tb_y", email=f"test_tb_{tag}+y@example.com")
        for i in range(2):
            assert _block(_mk("tutor", f"s12tbb{i}"), x["id"], "spam").status_code == 200
        assert requests.get(f"{API}/auth/me", headers=x["h"]).status_code == 423
        assert requests.delete(f"{API}/auth/me", headers=x["h"]).status_code == 200
        yy = requests.get(f"{API}/auth/me", headers=y["h"]).status_code
        assert requests.delete(f"{API}/auth/me", headers=y["h"]).status_code == 200
        r = requests.post(f"{API}/auth/signup", headers=_ip(), json={"email": f"test_tb_{tag}+z@example.com", "password": "password123", "name": "TEST_s12tb_z", "role": "parent"})
        if r.status_code == 201:
            CREATED.append({"id": r.json()["user"]["id"], "h": {"Authorization": f"Bearer {r.json()['access_token']}"}})
        assert r.status_code == 423, f"tombstone downgraded by deleting alias Y (y /me={yy}); re-signup got {r.status_code}"


def _db():
    from pymongo import MongoClient
    env = dict(l.strip().split("=", 1) for l in open("/app/backend/.env") if "=" in l)
    return MongoClient(env["MONGO_URL"].strip('"'))[env["DB_NAME"].strip('"')]
