"""Admin dashboards: stats, earnings, analytics events, users."""
from typing import Optional

from fastapi import APIRouter, Depends

from core import db, require_admin

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
