"""Admin dashboards: stats, earnings, analytics events, users."""
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core import db, now_iso, require_admin

router = APIRouter()


def _cap(limit: int, most: int = 500) -> int:
    return min(max(limit, 1), most)


async def _earnings_total() -> int:
    rows = await db.platform_earnings.aggregate([{"$group": {"_id": None, "total": {"$sum": "$amount_cents"}}}]).to_list(1)
    return int(rows[0]["total"] or 0) if rows else 0


@router.get("/admin/stats")
async def admin_stats(u: dict = Depends(require_admin)):
    return {
        "users": await db.users.count_documents({}),
        "parents": await db.users.count_documents({"role": "parent"}),
        "tutors": await db.users.count_documents({"role": "tutor"}),
        "bookings": await db.bookings.count_documents({}),
        "paid_bookings": await db.bookings.count_documents({"payment_status": "paid"}),
        "canceled_bookings": await db.bookings.count_documents({"payment_status": "canceled"}),
        "pending_verifications": await db.tutors.count_documents({"verification_status": "pending"}),
        "messages": await db.messages.count_documents({}),
        "open_message_flags": await db.message_flags.count_documents({"status": "open"}),
        "reviews": await db.reviews.count_documents({}),
        "favorites": await db.favorites.count_documents({}),
        "events": await db.events.count_documents({}),
        "platform_earnings_cents": await _earnings_total(),
        "platform_earnings_count": await db.platform_earnings.count_documents({"kind": {"$ne": "reversal"}}),
    }


@router.get("/admin/earnings")
async def admin_earnings(u: dict = Depends(require_admin), limit: int = 50):
    docs = await db.platform_earnings.find({}, {"_id": 0}).sort("at", -1).to_list(_cap(limit))
    return {"total_cents": await _earnings_total(), "count": await db.platform_earnings.count_documents({}), "entries": docs}


@router.get("/admin/events")
async def admin_events(u: dict = Depends(require_admin), limit: int = 100, name: Optional[str] = None):
    q = {"name": name} if name else {}
    docs = await db.events.find(q, {"_id": 0}).sort("at", -1).to_list(_cap(limit))
    counts = await db.events.aggregate([
        {"$group": {"_id": "$name", "count": {"$sum": 1}}}, {"$sort": {"count": -1}}, {"$limit": 20},
    ]).to_list(20)
    return {"events": docs, "counts": [{"name": c["_id"], "count": c["count"]} for c in counts]}


@router.get("/admin/users")
async def admin_users(u: dict = Depends(require_admin), limit: int = 100):
    return await db.users.find({}, {"_id": 0, "password_hash": 0}).sort("created_at", -1).to_list(_cap(limit))


# ---- Message safety: messages that shared contact or payment details before a booking ----
class FlagResolve(BaseModel):
    outcome: Literal["fine", "reviewed"]
    note: Optional[str] = Field(default="", max_length=500)


@router.get("/admin/message-flags")
async def admin_message_flags(u: dict = Depends(require_admin), status: Literal["open", "resolved"] = "open", limit: int = 100):
    flags = await db.message_flags.find({"status": status}, {"_id": 0}).sort("created_at", -1).to_list(_cap(limit))
    ids = list({f["from_user_id"] for f in flags} | {f["to_user_id"] for f in flags})
    people = {p["id"]: p for p in await db.users.find(
        {"id": {"$in": ids}}, {"_id": 0, "id": 1, "name": 1, "role": 1, "suspended": 1}).to_list(len(ids) or 1)}
    totals: dict = {}
    for f in flags:
        sender = f["from_user_id"]
        if sender not in totals:
            totals[sender] = await db.message_flags.count_documents({"from_user_id": sender})
    for f in flags:
        f["from_user"] = people.get(f["from_user_id"])
        f["to_user"] = people.get(f["to_user_id"])
        f["sender_flag_count"] = totals[f["from_user_id"]]
    return {"flags": flags, "open_count": await db.message_flags.count_documents({"status": "open"})}


@router.post("/admin/message-flags/{flag_id}/resolve")
async def resolve_message_flag(flag_id: str, body: FlagResolve, u: dict = Depends(require_admin)):
    res = await db.message_flags.update_one({"id": flag_id, "status": "open"}, {"$set": {
        "status": "resolved", "outcome": body.outcome, "note": body.note or "",
        "resolved_by": u["id"], "resolved_at": now_iso(),
    }})
    if res.matched_count == 0:
        raise HTTPException(404, "That item was already reviewed.")
    return {"ok": True}
