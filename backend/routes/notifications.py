"""In-app notification feed (push delivery happens in core.push_notification)."""
from typing import List

from fastapi import APIRouter, Depends

from core import current_user, db
from models import NotificationOut
from workers import generate_for_user

router = APIRouter()


@router.get("/notifications", response_model=List[NotificationOut])
async def my_notifications(u: dict = Depends(current_user)):
    # The worker creates these every minute too; doing it here as well keeps the feed instant.
    await generate_for_user(u)
    docs = await db.notifications.find({"user_id": u["id"]}, {"_id": 0}).sort("at", -1).to_list(50)
    return [NotificationOut(**d) for d in docs]


@router.post("/notifications/read-all")
async def read_all(u: dict = Depends(current_user)):
    await db.notifications.update_many({"user_id": u["id"]}, {"$set": {"read": True}})
    return {"ok": True}
