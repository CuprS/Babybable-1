"""Family profiles, favourites and analytics events."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from starlette.concurrency import run_in_threadpool

from core import blocked_between, current_user, db, geocode, now_iso
from models import Child, EventIn, ParentProfile, ParentProfileUpdate
from routes.messages import users_have_relationship

router = APIRouter()


def parent_doc_to_model(p: dict, name: str) -> ParentProfile:
    return ParentProfile(
        user_id=p["user_id"], name=p.get("name") or name, avatar_url=p.get("avatar_url"),
        city=p.get("city", ""), latitude=p.get("latitude"), longitude=p.get("longitude"),
        languages_desired=p.get("languages_desired", []), hours_per_week=p.get("hours_per_week", 5),
        learning_materials=p.get("learning_materials", ""),
        children=[Child(**c) for c in p.get("children", [])],
    )


async def _geocode_city_if_changed(user_id: str, city: str, previous: Optional[dict]) -> None:
    if not city:
        return
    prev = (previous or {}).get("city") or ""
    if prev.strip().lower() == city.strip().lower() and (previous or {}).get("latitude") is not None:
        return
    coords = await run_in_threadpool(geocode, city)
    if coords:
        await db.parents.update_one({"user_id": user_id}, {"$set": coords})


@router.get("/parents/me/profile", response_model=ParentProfile)
async def get_parent_profile(u: dict = Depends(current_user)):
    if u["role"] != "parent":
        raise HTTPException(403, "Only parents")
    doc = await db.parents.find_one({"user_id": u["id"]}, {"_id": 0})
    if not doc:
        doc = {
            "user_id": u["id"], "name": u["name"], "avatar_url": u.get("avatar_url"),
            "city": "", "languages_desired": [], "hours_per_week": 5,
            "learning_materials": "", "children": [], "created_at": now_iso(),
        }
        await db.parents.insert_one(dict(doc))
    return parent_doc_to_model(doc, u["name"])


@router.patch("/parents/me/profile", response_model=ParentProfile)
async def update_parent_profile(patch: ParentProfileUpdate, u: dict = Depends(current_user)):
    if u["role"] != "parent":
        raise HTTPException(403, "Only parents")
    prev = await db.parents.find_one({"user_id": u["id"]}, {"_id": 0}) or {}
    update = patch.model_dump(exclude_none=True)
    if update:
        await db.parents.update_one({"user_id": u["id"]}, {"$set": update}, upsert=True)
        user_patch = {k: v for k, v in update.items() if k in ("name", "avatar_url")}
        if user_patch:
            await db.users.update_one({"id": u["id"]}, {"$set": user_patch})
        if "city" in update:
            await _geocode_city_if_changed(u["id"], update["city"], prev)
    doc = await db.parents.find_one({"user_id": u["id"]}, {"_id": 0})
    fresh = await db.users.find_one({"id": u["id"]}, {"_id": 0})
    return parent_doc_to_model(doc, fresh["name"] if fresh else u["name"])


@router.get("/parents/{user_id}/public", response_model=ParentProfile)
async def get_parent_public(user_id: str, u: dict = Depends(current_user)):
    """Non-owners see children names + ages but NEVER their photos or the exact location."""
    parent = await db.parents.find_one({"user_id": user_id}, {"_id": 0})
    if not parent:
        raise HTTPException(404, "Parent profile not found")
    fresh = await db.users.find_one({"id": user_id}, {"_id": 0})
    if not fresh:
        raise HTTPException(404, "User not found")
    is_owner = u["id"] == user_id
    if not is_owner and not u.get("is_admin"):
        if await blocked_between(u["id"], user_id):
            raise HTTPException(404, "Parent profile not found")
        # Only tutors the family booked with or chatted with may view the profile.
        if u.get("role") != "tutor" or not await users_have_relationship(u["id"], user_id, parent_must_reach_out=True):
            raise HTTPException(403, "This family profile is only visible to their tutors")
    if not is_owner:
        parent = {**parent, "latitude": None, "longitude": None}
        parent["children"] = [{**c, "avatar_url": None} for c in parent.get("children", [])]
    return parent_doc_to_model(parent, fresh["name"])


@router.post("/events")
async def track_event(body: EventIn, u: dict = Depends(current_user)):
    await db.events.insert_one({
        "user_id": u["id"], "role": u["role"], "user_name": u["name"], "name": body.name,
        "props": body.props or {}, "at": now_iso(),
    })
    return {"ok": True}


@router.post("/favorites/{tutor_id}")
async def add_fav(tutor_id: str, u: dict = Depends(current_user)):
    if u["role"] != "parent":
        raise HTTPException(403, "Only parents")
    if not await db.tutors.find_one({"id": tutor_id}, {"_id": 1}):
        raise HTTPException(404, "Tutor not found")
    await db.favorites.update_one(
        {"user_id": u["id"], "tutor_id": tutor_id},
        {"$set": {"user_id": u["id"], "tutor_id": tutor_id, "at": now_iso()}},
        upsert=True,
    )
    return {"saved": True}


@router.delete("/favorites/{tutor_id}")
async def remove_fav(tutor_id: str, u: dict = Depends(current_user)):
    await db.favorites.delete_one({"user_id": u["id"], "tutor_id": tutor_id})
    return {"saved": False}


@router.get("/favorites")
async def list_favs(u: dict = Depends(current_user)):
    rows = await db.favorites.find({"user_id": u["id"]}, {"_id": 0, "tutor_id": 1}).to_list(500)
    return [r["tutor_id"] for r in rows]
