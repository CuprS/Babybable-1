"""Reviews: only verified customers, one per session."""
import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException

from core import blocked_between, booking_start_utc, current_user, db, now_iso, now_utc
from models import Review, ReviewCreate

router = APIRouter()


async def recompute_tutor_rating(tutor_id: str) -> None:
    agg = await db.reviews.aggregate([
        {"$match": {"tutor_id": tutor_id}},
        {"$group": {"_id": None, "avg": {"$avg": "$rating"}, "n": {"$sum": 1}}},
    ]).to_list(1)
    avg, n = (agg[0]["avg"], agg[0]["n"]) if agg else (0.0, 0)
    await db.tutors.update_one({"id": tutor_id}, {"$set": {"rating": round(avg, 2), "reviews_count": n}})


@router.post("/reviews", response_model=Review)
async def create_review(body: ReviewCreate, u: dict = Depends(current_user)):
    if u["role"] != "parent":
        raise HTTPException(403, "Only parents can review")
    t = await db.tutors.find_one({"id": body.tutor_id}, {"_id": 0, "user_id": 1})
    if not t or await blocked_between(u["id"], t["user_id"]):
        raise HTTPException(404, "Tutor not found")
    # Only verified customers: a paid booking of yours, with this tutor, that has started.
    b = await db.bookings.find_one(
        {"id": body.booking_id, "parent_id": u["id"], "tutor_id": body.tutor_id, "payment_status": "paid"},
        {"_id": 0},
    )
    if not b:
        raise HTTPException(403, "You can only review a tutor after a paid session with them.")
    start = booking_start_utc(b)
    if start and start > now_utc():
        raise HTTPException(400, "You can review this session once it has taken place.")
    if await db.reviews.find_one({"booking_id": body.booking_id}, {"_id": 1}):
        raise HTTPException(409, "You've already reviewed this session.")
    r = {
        "id": str(uuid.uuid4()), "tutor_id": body.tutor_id, "booking_id": body.booking_id,
        "parent_id": u["id"], "parent_name": u["name"], "rating": body.rating,
        "comment": body.comment.strip(), "created_at": now_iso(),
    }
    await db.reviews.insert_one(r)
    await recompute_tutor_rating(body.tutor_id)
    r.pop("_id", None)
    return Review(**r)


@router.get("/reviews/tutor/{tutor_id}", response_model=List[Review])
async def tutor_reviews(tutor_id: str):
    docs = await db.reviews.find({"tutor_id": tutor_id}, {"_id": 0}).sort("created_at", -1).to_list(200)
    return [Review(**d) for d in docs]
