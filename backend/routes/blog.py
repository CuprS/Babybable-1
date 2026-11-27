"""Blog: tutor-contributed articles + admin moderation."""
from datetime import datetime, timezone
from typing import List, Optional, Literal
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core import db, current_user, optional_user, require_admin, require_verified_email, push_notification as _push


async def push_notification(user_id: str, kind: str, title: str, body: str) -> None:
    if user_id != EDITORIAL_AUTHOR_ID:  # editorial posts have no real author account
        await _push(user_id, kind, title, body)

router = APIRouter()


# ---- Blog posts (tutor contributions) ----
MAX_POST_IMAGES = 2
PostStatus = Literal["pending", "published", "rejected"]


class PostCreate(BaseModel):
    title: str = Field(min_length=4, max_length=160)
    excerpt: Optional[str] = Field(default="", max_length=300)
    body: str = Field(min_length=40, max_length=20000)
    tag: Optional[str] = Field(default="", max_length=40)
    image_urls: List[str] = Field(default_factory=list, max_length=MAX_POST_IMAGES)


class PostUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=4, max_length=160)
    excerpt: Optional[str] = Field(default=None, max_length=300)
    body: Optional[str] = Field(default=None, min_length=40, max_length=20000)
    tag: Optional[str] = Field(default=None, max_length=40)
    image_urls: Optional[List[str]] = Field(default=None, max_length=MAX_POST_IMAGES)


class Post(BaseModel):
    id: str
    author_id: str
    author_name: str
    author_avatar_url: Optional[str] = None
    title: str
    excerpt: str
    body: str
    cover_image_url: Optional[str] = ""
    tag: str = ""
    image_urls: List[str] = []
    status: PostStatus
    reviewer_notes: Optional[str] = ""
    submitted_at: str
    reviewed_at: Optional[str] = None
    published_at: Optional[str] = None
    updated_at: str


class PostReview(BaseModel):
    reviewer_notes: Optional[str] = Field(default="", max_length=600)


# ---- Blog posts ----
def post_doc_to_model(d: dict) -> Post:
    data = {k: d.get(k) for k in Post.model_fields.keys()}
    data["image_urls"] = d.get("image_urls") or []
    return Post(**data)


async def _clean_images(urls: List[str], owner_id: str) -> List[str]:
    """Only accept storage paths the author uploaded themselves (max 2)."""
    out = [u.strip() for u in urls if u and u.strip()]
    if len(out) > MAX_POST_IMAGES:
        raise HTTPException(422, f"Up to {MAX_POST_IMAGES} photos per article")
    for path in out:
        if not await db.uploads.find_one({"path": path, "owner_id": owner_id}, {"_id": 1}):
            raise HTTPException(422, "Photos must be uploaded from your device")
    return out


@router.post("/posts", response_model=Post, status_code=201)
async def create_post(body: PostCreate, u: dict = Depends(current_user)):
    if u.get("role") != "tutor":
        raise HTTPException(403, "Only tutors can submit blog articles")
    require_verified_email(u)
    images = await _clean_images(body.image_urls, u["id"])
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "id": str(uuid.uuid4()),
        "author_id": u["id"],
        "author_name": u["name"],
        "author_avatar_url": u.get("avatar_url"),
        "title": body.title.strip(),
        "excerpt": (body.excerpt or body.body)[:300].strip(),
        "body": body.body.strip(),
        "cover_image_url": images[0] if images else "",
        "tag": (body.tag or "").strip(),
        "image_urls": images,
        "status": "pending",
        "reviewer_notes": "",
        "submitted_at": now,
        "reviewed_at": None,
        "published_at": None,
        "updated_at": now,
    }
    await db.posts.insert_one(doc)
    return post_doc_to_model(doc)


@router.get("/posts", response_model=List[Post])
async def list_posts(tag: Optional[str] = None, limit: int = 50):
    """Public — only PUBLISHED posts, newest first."""
    query: dict = {"status": "published"}
    if tag:
        query["tag"] = {"$regex": f"^{re.escape(tag)[:40]}$", "$options": "i"}
    docs = await db.posts.find(query, {"_id": 0, "body": 0}).sort("published_at", -1).to_list(min(max(limit, 1), 100))
    # body stripped for list view — fetch full post via /posts/{id}
    return [post_doc_to_model({**d, "body": ""}) for d in docs]


@router.get("/posts/me", response_model=List[Post])
async def my_posts(u: dict = Depends(current_user)):
    if u.get("role") != "tutor":
        raise HTTPException(403, "Only tutors have submissions")
    docs = await db.posts.find({"author_id": u["id"]}, {"_id": 0}).sort("submitted_at", -1).to_list(200)
    return [post_doc_to_model(d) for d in docs]


@router.get("/posts/{post_id}", response_model=Post)
async def get_post(post_id: str, u_maybe: Optional[dict] = Depends(optional_user)):
    d = await db.posts.find_one({"id": post_id}, {"_id": 0})
    if not d:
        raise HTTPException(404, "Post not found")
    if d["status"] != "published":
        # Only author or admin can see non-published drafts.
        if not u_maybe or (u_maybe["id"] != d["author_id"] and not u_maybe.get("is_admin")):
            raise HTTPException(404, "Post not found")
    return post_doc_to_model(d)


@router.patch("/posts/{post_id}", response_model=Post)
async def update_post(post_id: str, patch: PostUpdate, u: dict = Depends(current_user)):
    d = await db.posts.find_one({"id": post_id}, {"_id": 0})
    if not d:
        raise HTTPException(404, "Post not found")
    if d["author_id"] != u["id"]:
        raise HTTPException(403, "Not your post")
    if d["status"] == "published":
        raise HTTPException(400, "Published posts can't be edited. Ask an admin to unpublish first.")
    update = {k: v for k, v in patch.model_dump(exclude_none=True).items() if v is not None}
    if "image_urls" in update:
        update["image_urls"] = await _clean_images(update["image_urls"], u["id"])
        update["cover_image_url"] = update["image_urls"][0] if update["image_urls"] else ""
    if not update:
        return post_doc_to_model(d)
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    # Any edit on a rejected post flips it back to pending for re-review.
    if d["status"] == "rejected":
        update["status"] = "pending"
        update["reviewer_notes"] = ""
        update["submitted_at"] = update["updated_at"]
    await db.posts.update_one({"id": post_id}, {"$set": update})
    fresh = await db.posts.find_one({"id": post_id}, {"_id": 0})
    return post_doc_to_model(fresh)


@router.delete("/posts/{post_id}")
async def delete_post(post_id: str, u: dict = Depends(current_user)):
    d = await db.posts.find_one({"id": post_id}, {"_id": 0, "author_id": 1, "status": 1})
    if not d:
        raise HTTPException(404, "Post not found")
    if d["author_id"] != u["id"] and not u.get("is_admin"):
        raise HTTPException(403, "Not your post")
    if d["status"] == "published" and not u.get("is_admin"):
        raise HTTPException(400, "Published posts can only be removed by an admin.")
    await db.posts.delete_one({"id": post_id})
    return {"deleted": True}


# ---- Admin blog moderation ----
@router.get("/admin/posts", response_model=List[Post])
async def admin_list_posts(
    status: Optional[str] = None,
    limit: int = 100,
    u: dict = Depends(require_admin),
):
    query: dict = {}
    if status and status in ("pending", "published", "rejected"):
        query["status"] = status
    docs = await db.posts.find(query, {"_id": 0}).sort("submitted_at", -1).to_list(min(max(limit, 1), 200))
    return [post_doc_to_model(d) for d in docs]


@router.post("/admin/posts/{post_id}/publish", response_model=Post)
async def admin_publish_post(post_id: str, body: Optional[PostReview] = None, u: dict = Depends(require_admin)):
    d = await db.posts.find_one({"id": post_id}, {"_id": 0})
    if not d:
        raise HTTPException(404, "Post not found")
    now = datetime.now(timezone.utc).isoformat()
    update = {
        "status": "published",
        "reviewed_at": now,
        "published_at": d.get("published_at") or now,
        "reviewer_notes": (body.reviewer_notes if body else "") or "",
        "updated_at": now,
    }
    await db.posts.update_one({"id": post_id}, {"$set": update})
    fresh = await db.posts.find_one({"id": post_id}, {"_id": 0})
    # Nudge the author.
    await push_notification(d["author_id"], "post", "Your article is live!", f"\"{d['title'][:60]}\" is published on Babybabel.")
    return post_doc_to_model(fresh)


@router.post("/admin/posts/{post_id}/reject", response_model=Post)
async def admin_reject_post(post_id: str, body: PostReview, u: dict = Depends(require_admin)):
    d = await db.posts.find_one({"id": post_id}, {"_id": 0})
    if not d:
        raise HTTPException(404, "Post not found")
    note = (body.reviewer_notes or "").strip()
    if not note:
        raise HTTPException(422, "Add a note telling the tutor what to change")
    now = datetime.now(timezone.utc).isoformat()
    update = {
        "status": "rejected",
        "reviewed_at": now,
        "reviewer_notes": note,
        "updated_at": now,
    }
    await db.posts.update_one({"id": post_id}, {"$set": update})
    fresh = await db.posts.find_one({"id": post_id}, {"_id": 0})
    await push_notification(d["author_id"], "post", "Article needs revisions", note[:140])
    return post_doc_to_model(fresh)


@router.post("/admin/posts/{post_id}/unpublish", response_model=Post)
async def admin_unpublish_post(post_id: str, u: dict = Depends(require_admin)):
    d = await db.posts.find_one({"id": post_id}, {"_id": 0})
    if not d:
        raise HTTPException(404, "Post not found")
    if d["status"] != "published":
        raise HTTPException(400, "Only published posts can be unpublished")
    now = datetime.now(timezone.utc).isoformat()
    await db.posts.update_one({"id": post_id}, {"$set": {
        "status": "pending",
        "reviewer_notes": "",
        "updated_at": now,
    }})
    fresh = await db.posts.find_one({"id": post_id}, {"_id": 0})
    await push_notification(d["author_id"], "post", "Article unpublished", f"\"{d['title'][:60]}\" is back in review.")
    return post_doc_to_model(fresh)


# ---- Editorial seed (shown before tutors contribute) ----
EDITORIAL_AUTHOR_ID = "babybabel-editorial"
EDITORIAL_POSTS = [
    {
        "id": "raising-bilingual", "tag": "Guides",
        "title": "Raising a bilingual toddler: five tiny rituals that actually work",
        "excerpt": "The Sunday-morning breakfast in Spanish. The bedtime story in French. Small, warm loops.",
        "cover_image_url": "https://images.unsplash.com/photo-1503454537195-1dcabb73ffb9?crop=entropy&cs=srgb&fm=jpg&q=85&w=1200",
        "body": "Fluency rarely comes from drills. It comes from repetition inside moments a child already loves.\n\n1. Pick one meal a week that happens entirely in the second language.\n2. Keep one bedtime book that is only ever read in that language.\n3. Name the weather together every morning.\n4. Sing while you tidy up — songs stick long after vocabulary lists fade.\n5. Let your tutor own one ritual of their own, so the language has a face and a voice.\n\nSmall, warm loops beat long, serious lessons every time.",
    },
    {
        "id": "why-mandarin-now", "tag": "Trends",
        "title": "Why families are choosing Mandarin — but starting with songs, not sentences",
        "excerpt": "The single biggest predictor of language fluency at age 8 has nothing to do with grammar.",
        "cover_image_url": "https://images.unsplash.com/photo-1544005313-94ddf0286df2?crop=entropy&cs=srgb&fm=jpg&q=85&w=1200",
        "body": "Mandarin is tonal, and young ears are wonderfully good at tones. That is why our Mandarin tutors start with music.\n\nNursery songs carry the rise and fall of each word far better than any chart. By the time sentences arrive, children already hear the melody of the language.\n\nThe biggest predictor of fluency at eight? Hours of joyful exposure before five.",
    },
    {
        "id": "small-languages", "tag": "Mission",
        "title": "The 'small' languages deserve big tutors",
        "excerpt": "Why Basque, Yoruba, and Tagalog belong on the same shelf as Spanish and French.",
        "cover_image_url": "https://images.unsplash.com/photo-1591123120675-6f7f1aae0e5b?crop=entropy&cs=srgb&fm=jpg&q=85&w=1200",
        "body": "Heritage languages carry grandparents' stories, recipes and jokes. When a family loses one, it rarely comes back.\n\nBabybabel welcomes tutors in every language, from Basque to Yoruba to Tagalog, because every child deserves to hear the voices of their family's history.",
    },
]


RETIRED_EDITORIAL_IDS = ("meet-marie",)  # spotlighted a fictional sample tutor


async def seed_editorial_posts() -> None:
    now = datetime.now(timezone.utc).isoformat()
    await db.posts.delete_many({"id": {"$in": list(RETIRED_EDITORIAL_IDS)}, "author_id": EDITORIAL_AUTHOR_ID})
    for p in EDITORIAL_POSTS:
        if await db.posts.find_one({"id": p["id"]}, {"_id": 1}):
            continue
        await db.posts.insert_one({
            **p, "author_id": EDITORIAL_AUTHOR_ID, "author_name": "Babybabel Team",
            "author_avatar_url": None, "image_urls": [], "status": "published",
            "reviewer_notes": "", "submitted_at": now, "reviewed_at": now,
            "published_at": now, "updated_at": now,
        })
