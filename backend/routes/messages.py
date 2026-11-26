"""Chat messages and tutor lesson invitations."""
import uuid
from datetime import timedelta
from typing import List

from fastapi import APIRouter, Depends, HTTPException

from booking_service import attach_payment_intent
from core import (
    BLOCKED_MSG, NOT_VERIFIED_MSG, TUTOR_NOT_VERIFIED_MSG, _normalize_slot, blocked_between, blocked_user_ids,
    current_user, db, is_tutor_verified,
    find_overlapping_booking, is_slot_allowed, now_iso, now_utc, platform_fee_for, push_notification,
    reject_past_slot, require_verified_email,
)
from models import Booking, InvitationCreate, Message, MessageCreate
from routes.bookings import insert_booking

router = APIRouter()

MSG_PER_MINUTE = 20
MSG_PER_DAY = 300
COLD_MSG_PER_DAY = 10


async def users_have_relationship(tutor_user_id: str, parent_user_id: str, parent_must_reach_out: bool = False) -> bool:
    """True if the tutor and parent share a booking or a chat. With parent_must_reach_out,
    only chats the family took part in count (a tutor's unanswered cold message doesn't)."""
    tutor = await db.tutors.find_one({"user_id": tutor_user_id}, {"_id": 0, "id": 1})
    if tutor and await db.bookings.find_one({"tutor_id": tutor["id"], "parent_id": parent_user_id}, {"_id": 1}):
        return True
    q = [{"from_user_id": parent_user_id, "to_user_id": tutor_user_id}]
    if not parent_must_reach_out:
        q.append({"from_user_id": tutor_user_id, "to_user_id": parent_user_id})
    return bool(await db.messages.find_one({"$or": q}, {"_id": 1}))


async def enforce_message_limits(u: dict, to_user: dict) -> bool:
    """Throttle chat spam. Returns True when this message opens a cold conversation
    (tutor -> family with no prior chat or booking)."""
    require_verified_email(u)
    if await blocked_between(u["id"], to_user["id"]):
        raise HTTPException(403, BLOCKED_MSG)
    now = now_utc()
    minute_ago = (now - timedelta(minutes=1)).isoformat()
    day_ago = (now - timedelta(days=1)).isoformat()
    if await db.messages.count_documents({"from_user_id": u["id"], "created_at": {"$gte": minute_ago}}) >= MSG_PER_MINUTE:
        raise HTTPException(429, "You're sending messages very quickly. Please wait a minute.", headers={"Retry-After": "60"})
    if await db.messages.count_documents({"from_user_id": u["id"], "created_at": {"$gte": day_ago}}) >= MSG_PER_DAY:
        raise HTTPException(429, f"Daily limit of {MSG_PER_DAY} messages reached. Try again tomorrow.")
    if u.get("role") != "tutor" or to_user.get("role") != "parent":
        return False
    if await users_have_relationship(u["id"], to_user["id"]):
        return False
    if await db.messages.count_documents({"from_user_id": u["id"], "cold": True, "created_at": {"$gte": day_ago}}) >= COLD_MSG_PER_DAY:
        raise HTTPException(429, f"You can contact {COLD_MSG_PER_DAY} new families per day. Try again tomorrow.")
    return True


@router.post("/messages", response_model=Message)
async def send_message(body: MessageCreate, u: dict = Depends(current_user)):
    to_user = await db.users.find_one({"id": body.to_user_id}, {"_id": 0, "id": 1, "role": 1})
    if not to_user:
        raise HTTPException(404, "Recipient not found")
    cold = await enforce_message_limits(u, to_user)
    m = {
        "id": str(uuid.uuid4()), "from_user_id": u["id"], "to_user_id": body.to_user_id,
        "text": body.text, "kind": "text", "invitation": None, "created_at": now_iso(),
    }
    await db.messages.insert_one({**m, "cold": cold})
    await push_notification(body.to_user_id, "chat", f"New message from {u['name']}", body.text[:120], {"from_user_id": u["id"]})
    return Message(**m)


@router.post("/messages/invitation", response_model=Message)
async def send_invitation(body: InvitationCreate, u: dict = Depends(current_user)):
    if u["role"] != "tutor":
        raise HTTPException(403, "Only tutors can send lesson invitations")
    to_user = await db.users.find_one({"id": body.to_user_id}, {"_id": 0, "id": 1, "role": 1})
    if not to_user or to_user.get("role") != "parent":
        raise HTTPException(404, "Recipient not found")
    my_tutor = await db.tutors.find_one({"user_id": u["id"]}, {"_id": 0})
    if not is_tutor_verified(my_tutor):
        raise HTTPException(403, TUTOR_NOT_VERIFIED_MSG)
    tz = (my_tutor or {}).get("timezone")
    reject_past_slot(body.date, body.time, tz)
    slot_time = _normalize_slot(body.time)
    cold = await enforce_message_limits(u, to_user)
    # Validate that the tutor isn't inviting outside their own calendar / on top of a booking.
    if my_tutor:
        if not is_slot_allowed(my_tutor, body.date, slot_time):
            raise HTTPException(400, "That slot is outside your weekly availability. Update it in your profile or pick another time.")
        if await find_overlapping_booking(my_tutor["id"], body.date, slot_time, body.duration_minutes):
            raise HTTPException(409, "You already have a session at that time.")
    inv = {
        "price_cents": body.price_cents, "date": body.date, "time": slot_time,
        "duration_minutes": body.duration_minutes, "language": body.language,
        "note": body.note or "", "status": "pending", "booking_id": None,
    }
    m = {
        "id": str(uuid.uuid4()), "from_user_id": u["id"], "to_user_id": body.to_user_id,
        "text": f"Lesson invitation · {body.language} · {body.date} {slot_time}",
        "kind": "invitation", "invitation": inv, "created_at": now_iso(),
    }
    await db.messages.insert_one({**m, "cold": cold})
    await push_notification(body.to_user_id, "invitation", f"Lesson invitation from {u['name']}",
                            f"{body.language} · {body.date} at {slot_time} · ${body.price_cents / 100:.0f}", {"from_user_id": u["id"]})
    return Message(**m)


@router.post("/messages/invitation/{message_id}/accept", response_model=Booking)
async def accept_invitation(message_id: str, u: dict = Depends(current_user)):
    if u["role"] != "parent":
        raise HTTPException(403, "Only parents can accept invitations")
    msg = await db.messages.find_one({"id": message_id}, {"_id": 0})
    if not msg or msg.get("kind") != "invitation":
        raise HTTPException(404, "Invitation not found")
    if msg["to_user_id"] != u["id"]:
        raise HTTPException(403, "Not your invitation")
    if await blocked_between(u["id"], msg["from_user_id"]):
        raise HTTPException(403, BLOCKED_MSG)
    inv = msg.get("invitation") or {}
    if inv.get("status") != "pending":
        raise HTTPException(400, f"Invitation is already {inv.get('status')}")
    t = await db.tutors.find_one({"user_id": msg["from_user_id"]}, {"_id": 0})
    if not t or t.get("suspended"):
        raise HTTPException(404, "Tutor profile not found")
    if not is_tutor_verified(t):
        raise HTTPException(400, NOT_VERIFIED_MSG)
    tz = t.get("timezone")
    reject_past_slot(inv["date"], inv["time"], tz)
    if await find_overlapping_booking(t["id"], inv["date"], inv["time"], inv["duration_minutes"]):
        raise HTTPException(409, "That slot is no longer available.")
    booking_id = str(uuid.uuid4())
    inv_base = int(inv["price_cents"])
    inv_fee = platform_fee_for(inv_base)
    booking = {
        "id": booking_id, "parent_id": u["id"], "parent_name": u["name"],
        "tutor_id": t["id"], "tutor_name": t["name"],
        "date": inv["date"], "time": _normalize_slot(inv["time"]), "timezone": tz,
        "duration_minutes": inv["duration_minutes"], "language": inv["language"],
        "amount_cents": inv_base + inv_fee, "platform_fee_cents": inv_fee,
        "currency": t.get("currency", "usd"), "payment_status": "pending",
        "stripe_payment_intent_id": None, "client_secret": None, "notes": inv.get("note", ""),
        "is_au_pair": False, "lessons_count": 1, "distance_miles": None,
        "remote": bool(t.get("allows_remote")), "housing_offered": "",
        "tutor_response": "accepted",  # the tutor proposed it, so it's already agreed
        "reschedule_count": 0, "created_at": now_iso(),
    }
    # Flip the invitation first (atomically) so a double-tap can't create two bookings.
    flipped = await db.messages.update_one(
        {"id": message_id, "invitation.status": "pending"},
        {"$set": {"invitation.status": "accepted", "invitation.booking_id": booking_id}},
    )
    if flipped.modified_count == 0:
        raise HTTPException(409, "This invitation was already answered.")
    await attach_payment_intent(booking, "invitation", {"invitation_message_id": message_id})
    try:
        await insert_booking(booking)
    except HTTPException:
        await db.messages.update_one({"id": message_id}, {"$set": {"invitation.status": "pending", "invitation.booking_id": None}})
        raise
    await push_notification(t["user_id"], "booking", "Invitation accepted", f"{u['name']} accepted your lesson invitation for {inv['date']}", {"booking_id": booking_id})
    return Booking(**booking)


@router.post("/messages/invitation/{message_id}/decline")
async def decline_invitation(message_id: str, u: dict = Depends(current_user)):
    msg = await db.messages.find_one({"id": message_id}, {"_id": 0})
    if not msg or msg.get("kind") != "invitation":
        raise HTTPException(404, "Invitation not found")
    if msg["to_user_id"] != u["id"]:
        raise HTTPException(403, "Not your invitation")
    res = await db.messages.update_one({"id": message_id, "invitation.status": "pending"}, {"$set": {"invitation.status": "declined"}})
    if res.modified_count == 0:
        raise HTTPException(400, "This invitation was already answered.")
    return {"declined": True}


@router.get("/messages/threads")
async def get_threads(u: dict = Depends(current_user)):
    docs = await db.messages.find(
        {"$or": [{"from_user_id": u["id"]}, {"to_user_id": u["id"]}]}, {"_id": 0},
    ).sort("created_at", -1).to_list(1000)
    hidden = await blocked_user_ids(u["id"])
    seen: dict = {}
    for d in docs:
        other = d["to_user_id"] if d["from_user_id"] == u["id"] else d["from_user_id"]
        if other in seen or other in hidden:
            continue
        seen[other] = {"other_user_id": other, "last_message": d["text"], "created_at": d["created_at"]}
    users = {x["id"]: x for x in await db.users.find({"id": {"$in": list(seen)}}, {"_id": 0, "id": 1, "name": 1, "avatar_url": 1, "role": 1}).to_list(len(seen) or 1)}
    result = []
    for other, info in seen.items():
        user = users.get(other)
        if user:
            info.update({"other_user_name": user["name"], "other_user_avatar": user.get("avatar_url"), "other_user_role": user["role"]})
        result.append(info)
    result.sort(key=lambda x: x["created_at"], reverse=True)
    return result


@router.get("/messages/thread/{other_user_id}", response_model=List[Message])
async def get_thread(other_user_id: str, u: dict = Depends(current_user)):
    if await blocked_between(u["id"], other_user_id):
        return []
    docs = await db.messages.find(
        {"$or": [
            {"from_user_id": u["id"], "to_user_id": other_user_id},
            {"from_user_id": other_user_id, "to_user_id": u["id"]},
        ]},
        {"_id": 0},
    ).sort("created_at", 1).to_list(500)
    return [Message(**d) for d in docs]
