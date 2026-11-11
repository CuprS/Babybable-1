"""User blocking: permanent, mutual hiding. Reasons are visible to admins only."""
from datetime import datetime, timezone
from typing import Literal, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from server import db, current_user, require_admin, blocked_between

router = APIRouter()

BlockReason = Literal["spam", "harassment", "inappropriate", "safety", "fake", "other"]


class BlockCreate(BaseModel):
    user_id: str
    reason: BlockReason
    details: Optional[str] = Field(default="", max_length=1000)


@router.post("/blocks")
async def block_user(body: BlockCreate, u: dict = Depends(current_user)):
    if body.user_id == u["id"]:
        raise HTTPException(400, "You can't block yourself")
    target = await db.users.find_one({"id": body.user_id}, {"_id": 0, "id": 1, "is_admin": 1})
    if not target:
        raise HTTPException(404, "User not found")
    if target.get("is_admin"):
        raise HTTPException(400, "The Babybabel team can't be blocked. Contact support instead.")
    details = (body.details or "").strip()
    if body.reason == "other" and len(details) < 10:
        raise HTTPException(422, "Please describe what happened (at least 10 characters)")
    if await db.blocks.find_one({"blocker_id": u["id"], "blocked_id": body.user_id}, {"_id": 1}):
        raise HTTPException(409, "You've already blocked this person")
    await db.blocks.insert_one({
        "id": str(uuid.uuid4()),
        "blocker_id": u["id"],
        "blocked_id": body.user_id,
        "reason": body.reason,
        "details": details,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return {"ok": True}


@router.get("/blocks/status/{user_id}")
async def block_status(user_id: str, u: dict = Depends(current_user)):
    """Whether two users are blocked — never reveals which side blocked."""
    return {"blocked": await blocked_between(u["id"], user_id)}


@router.get("/admin/blocks")
async def admin_list_blocks(_: dict = Depends(require_admin)):
    docs = await db.blocks.find({}, {"_id": 0}).sort("created_at", -1).to_list(500)
    ids = {d["blocker_id"] for d in docs} | {d["blocked_id"] for d in docs}
    users = {x["id"]: x for x in await db.users.find(
        {"id": {"$in": list(ids)}}, {"_id": 0, "id": 1, "name": 1, "email": 1, "role": 1}
    ).to_list(len(ids) or 1)}
    counts: dict = {}
    for d in docs:
        counts[d["blocked_id"]] = counts.get(d["blocked_id"], 0) + 1
    for d in docs:
        d["blocker"] = users.get(d["blocker_id"])
        d["blocked"] = users.get(d["blocked_id"])
        d["times_blocked"] = counts[d["blocked_id"]]
    return docs
