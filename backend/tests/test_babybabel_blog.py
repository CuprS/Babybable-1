"""Session-10: Tutor contribution blog (public list/detail, tutor CRUD, admin moderation)."""
import io
import os
import uuid

import pytest
import requests

BASE = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or "https://papyrus-tutors.preview.emergentagent.com").rstrip("/")
API = f"{BASE}/api"
EDITORIAL_IDS = {"raising-bilingual", "why-mandarin-now", "meet-marie", "small-languages"}
BODY = "This is a TEST article body that is long enough to pass the 40 char minimum."
PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
       b"\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")


def _login(email, pw):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=20)
    if r.status_code != 200:
        pytest.skip(f"login failed for {email}: {r.status_code} {r.text[:120]}")
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def tokens():
    return {
        "admin": _login("copperstone17@gmail.com", "REDACTED-PASSWORD"),
        "sofia": _login("sofia@babybabel.dev", "password123"),
        "marie": _login("marie@babybabel.dev", "password123"),
        "parent": _login("parent@test.dev", "password123"),
    }


def _upload(h):
    r = requests.post(f"{API}/uploads", headers=h, files={"file": ("t.png", io.BytesIO(PNG), "image/png")}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["path"]


@pytest.fixture(scope="module")
def created(tokens):
    ids = []
    yield ids
    for pid in ids:
        requests.delete(f"{API}/posts/{pid}", headers=tokens["admin"], timeout=20)


def _create(tokens, created, **kw):
    payload = {"title": f"TEST_{uuid.uuid4().hex[:6]} article", "body": BODY, "tag": "Activities", **kw}
    r = requests.post(f"{API}/posts", headers=tokens["sofia"], json=payload, timeout=20)
    if r.status_code == 201:
        created.append(r.json()["id"])
    return r


# Public list / detail
class TestPublic:
    def test_list_public_has_editorial(self):
        r = requests.get(f"{API}/posts", timeout=20)
        assert r.status_code == 200
        data = r.json()
        ids = {p["id"] for p in data}
        assert EDITORIAL_IDS <= ids
        assert all(p["status"] == "published" for p in data)
        ed = [p for p in data if p["id"] in EDITORIAL_IDS]
        assert all(p["author_name"] == "Babybabel Team" for p in ed)
        assert all(p["body"] == "" for p in data)

    def test_list_tag_filter(self):
        r = requests.get(f"{API}/posts", params={"tag": "guides"}, timeout=20)
        assert r.status_code == 200
        assert all(p["tag"].lower() == "guides" for p in r.json())
        assert "raising-bilingual" in {p["id"] for p in r.json()}

    def test_detail_public(self):
        r = requests.get(f"{API}/posts/raising-bilingual", timeout=20)
        assert r.status_code == 200
        assert len(r.json()["body"]) > 40

    def test_detail_404(self):
        assert requests.get(f"{API}/posts/nope-{uuid.uuid4().hex}", timeout=20).status_code == 404


# Tutor create rules
class TestCreate:
    def test_parent_forbidden(self, tokens):
        r = requests.post(f"{API}/posts", headers=tokens["parent"], json={"title": "TEST_parent", "body": BODY}, timeout=20)
        assert r.status_code == 403

    def test_anon_unauthorized(self):
        r = requests.post(f"{API}/posts", json={"title": "TEST_anon", "body": BODY}, timeout=20)
        assert r.status_code == 401

    def test_three_images_422(self, tokens, created):
        p = _upload(tokens["sofia"])
        r = _create(tokens, created, image_urls=[p, p, p])
        assert r.status_code == 422

    def test_foreign_image_422(self, tokens, created):
        p = _upload(tokens["marie"])
        r = _create(tokens, created, image_urls=[p])
        assert r.status_code == 422
        r2 = _create(tokens, created, image_urls=["https://evil.example/x.jpg"])
        assert r2.status_code == 422

    def test_create_with_two_images_and_privacy(self, tokens, created):
        p1, p2 = _upload(tokens["sofia"]), _upload(tokens["sofia"])
        r = _create(tokens, created, image_urls=[p1, p2])
        assert r.status_code == 201, r.text
        d = r.json()
        assert d["status"] == "pending" and d["cover_image_url"] == p1 and d["image_urls"] == [p1, p2]
        assert d["excerpt"]  # defaults to body slice
        pid = d["id"]
        # pending hidden from public / other users, visible to author/admin
        assert requests.get(f"{API}/posts/{pid}", timeout=20).status_code == 404
        assert requests.get(f"{API}/posts/{pid}", headers=tokens["parent"], timeout=20).status_code == 404
        assert requests.get(f"{API}/posts/{pid}", headers=tokens["sofia"], timeout=20).status_code == 200
        assert requests.get(f"{API}/posts/{pid}", headers=tokens["admin"], timeout=20).status_code == 200
        assert pid not in {p["id"] for p in requests.get(f"{API}/posts", timeout=20).json()}
        mine = requests.get(f"{API}/posts/me", headers=tokens["sofia"], timeout=20).json()
        assert pid in {p["id"] for p in mine}

    def test_posts_me_parent_403(self, tokens):
        assert requests.get(f"{API}/posts/me", headers=tokens["parent"], timeout=20).status_code == 403


# Edit / delete / moderation lifecycle
class TestLifecycle:
    def test_full_lifecycle(self, tokens, created):
        r = _create(tokens, created)
        assert r.status_code == 201
        pid = r.json()["id"]
        # non-author patch 403
        assert requests.patch(f"{API}/posts/{pid}", headers=tokens["marie"], json={"title": "TEST_hack"}, timeout=20).status_code == 403
        # admin-only endpoints
        for h in (tokens["sofia"], tokens["parent"]):
            assert requests.get(f"{API}/admin/posts", headers=h, timeout=20).status_code == 403
            assert requests.post(f"{API}/admin/posts/{pid}/publish", headers=h, timeout=20).status_code == 403
        pend = requests.get(f"{API}/admin/posts", params={"status": "pending"}, headers=tokens["admin"], timeout=20).json()
        assert pid in {p["id"] for p in pend} and all(p["status"] == "pending" for p in pend)
        # reject
        rr = requests.post(f"{API}/admin/posts/{pid}/reject", headers=tokens["admin"], json={"reviewer_notes": "TEST please add more"}, timeout=20)
        assert rr.status_code == 200 and rr.json()["status"] == "rejected" and rr.json()["reviewer_notes"] == "TEST please add more"
        notifs = requests.get(f"{API}/notifications", headers=tokens["sofia"], timeout=20).json()
        assert any(n.get("title") == "Article needs revisions" for n in notifs)
        # edit rejected -> pending, notes cleared
        pr = requests.patch(f"{API}/posts/{pid}", headers=tokens["sofia"], json={"title": "TEST_revised title"}, timeout=20)
        assert pr.status_code == 200 and pr.json()["status"] == "pending" and pr.json()["reviewer_notes"] == ""
        # publish
        pb = requests.post(f"{API}/admin/posts/{pid}/publish", headers=tokens["admin"], timeout=20)
        assert pb.status_code == 200 and pb.json()["status"] == "published" and pb.json()["published_at"]
        assert requests.get(f"{API}/posts/{pid}", timeout=20).status_code == 200
        assert pid in {p["id"] for p in requests.get(f"{API}/posts", timeout=20).json()}
        notifs = requests.get(f"{API}/notifications", headers=tokens["sofia"], timeout=20).json()
        assert any(n.get("title") == "Your article is live!" for n in notifs)
        # author can't edit / delete published
        assert requests.patch(f"{API}/posts/{pid}", headers=tokens["sofia"], json={"title": "TEST_x title"}, timeout=20).status_code == 400
        assert requests.delete(f"{API}/posts/{pid}", headers=tokens["sofia"], timeout=20).status_code == 400
        # unpublish
        up = requests.post(f"{API}/admin/posts/{pid}/unpublish", headers=tokens["admin"], timeout=20)
        assert up.status_code == 200 and up.json()["status"] == "pending"
        assert requests.get(f"{API}/posts/{pid}", timeout=20).status_code == 404
        # author deletes non-published
        assert requests.delete(f"{API}/posts/{pid}", headers=tokens["marie"], timeout=20).status_code == 403
        d = requests.delete(f"{API}/posts/{pid}", headers=tokens["sofia"], timeout=20)
        assert d.status_code == 200 and d.json()["deleted"] is True
        assert requests.get(f"{API}/posts/{pid}", headers=tokens["admin"], timeout=20).status_code == 404

    def test_admin_delete_published(self, tokens, created):
        pid = _create(tokens, created).json()["id"]
        requests.post(f"{API}/admin/posts/{pid}/publish", headers=tokens["admin"], timeout=20)
        assert requests.delete(f"{API}/posts/{pid}", headers=tokens["admin"], timeout=20).status_code == 200
        assert requests.get(f"{API}/posts/{pid}", timeout=20).status_code == 404

    def test_admin_filters(self, tokens):
        for s in ("published", "rejected"):
            r = requests.get(f"{API}/admin/posts", params={"status": s}, headers=tokens["admin"], timeout=20)
            assert r.status_code == 200 and all(p["status"] == s for p in r.json())

    def test_missing_post_admin_actions_404(self, tokens):
        bad = f"nope-{uuid.uuid4().hex}"
        assert requests.post(f"{API}/admin/posts/{bad}/publish", headers=tokens["admin"], timeout=20).status_code == 404
        assert requests.post(f"{API}/admin/posts/{bad}/reject", headers=tokens["admin"], json={"reviewer_notes": "x"}, timeout=20).status_code == 404

    def test_patch_images_rules(self, tokens, created):
        pid = _create(tokens, created).json()["id"]
        p = _upload(tokens["sofia"])
        r = requests.patch(f"{API}/posts/{pid}", headers=tokens["sofia"], json={"image_urls": [p]}, timeout=20)
        assert r.status_code == 200 and r.json()["cover_image_url"] == p
        foreign = _upload(tokens["marie"])
        assert requests.patch(f"{API}/posts/{pid}", headers=tokens["sofia"], json={"image_urls": [foreign]}, timeout=20).status_code == 422
