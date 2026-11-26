"""Bookings: create, pay (mock / Stripe webhook), tutor accept/decline, cancel, reschedule."""
import os
import uuid
from datetime import timedelta
from typing import List, Optional

import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pymongo.errors import DuplicateKeyError

from booking_service import attach_payment_intent, cancel_booking, refund_policy
from core import (
    CANCEL_FULL_REFUND_HOURS, NOT_VERIFIED_MSG, RESCHEDULE_MIN_HOURS, TUTOR_RESPONSE_HOURS, _normalize_slot,
    blocked_between, is_tutor_verified,
    booking_start_utc, credit_platform_fee, current_user, db, find_overlapping_booking, haversine_miles,
    is_slot_allowed, now_iso, now_utc, platform_fee_for, push_notification, reject_past_slot,
    require_verified_email, slot_key, tutor_profile_id, tutor_user_id,
)
from models import Booking, BookingCreate, CancelRequest, RescheduleRequest, RespondRequest

router = APIRouter()


async def insert_booking(booking: dict) -> None:
    """Insert, letting the unique slot_key index reject a same-start double booking."""
    if not booking.get("is_au_pair"):
        booking["slot_key"] = slot_key(booking["tutor_id"], booking["date"], booking["time"])
    try:
        await db.bookings.insert_one(booking)
    except DuplicateKeyError:
        raise HTTPException(409, "That slot was just booked by someone else. Please pick another time.")
    booking.pop("_id", None)


async def _load_for(booking_id: str, u: dict) -> tuple[dict, str]:
    """Fetch a booking and the caller's side of it ('parent' | 'tutor' | 'admin')."""
    b = await db.bookings.find_one({"id": booking_id}, {"_id": 0})
    if not b:
        raise HTTPException(404, "Booking not found")
    if b["parent_id"] == u["id"]:
        return b, "parent"
    if u["role"] == "tutor" and b["tutor_id"] == await tutor_profile_id(u["id"]):
        return b, "tutor"
    if u.get("is_admin"):
        return b, "admin"
    raise HTTPException(403, "Not your booking")


@router.post("/bookings", response_model=Booking)
async def create_booking(body: BookingCreate, u: dict = Depends(current_user)):
    if u["role"] != "parent":
        raise HTTPException(403, "Only parents can book")
    require_verified_email(u)
    t = await db.tutors.find_one({"id": body.tutor_id}, {"_id": 0})
    if not t or t.get("suspended") or await blocked_between(u["id"], t["user_id"]):
        raise HTTPException(404, "Tutor not found")
    if not is_tutor_verified(t):
        raise HTTPException(400, NOT_VERIFIED_MSG)
    tz = t.get("timezone") or None  # session times are in the tutor's zone
    reject_past_slot(body.date, body.time, tz)
    slot_time = _normalize_slot(body.time)
    p = await db.parents.find_one({"user_id": u["id"]}, {"_id": 0}) or {}
    remote = bool(t.get("allows_remote"))
    au_pair = bool(body.is_au_pair)
    # Distance to the CLOSEST tutor location.
    distance: Optional[float] = None
    if p.get("latitude") is not None:
        candidates = [(loc["latitude"], loc["longitude"]) for loc in (t.get("locations") or []) if loc.get("latitude") is not None]
        if not candidates and t.get("latitude") is not None:
            candidates.append((t["latitude"], t["longitude"]))
        if candidates:
            distance = round(min(haversine_miles(lat, lng, p["latitude"], p["longitude"]) for lat, lng in candidates), 1)
    if au_pair:
        if body.lessons_count < 30:
            raise HTTPException(400, "Au-pair bookings require a minimum of 30 lessons")
    elif not remote:
        if distance is None:
            raise HTTPException(400, "Please set your city in your family profile so we can verify you're within 100 miles of this tutor.")
        if distance > 100:
            raise HTTPException(400, f"This tutor is {distance} miles away — over the 100-mile limit for in-person lessons. Book them for remote lessons or an au-pair stay instead.")
    lessons = max(1, body.lessons_count)
    base_amount = ((t["hourly_rate_cents"] * body.duration_minutes + 59) // 60) * lessons
    fee = platform_fee_for(base_amount)
    # Weekly availability + overlap with existing sessions. Skipped for au-pair (long-form stays).
    if not au_pair:
        if not is_slot_allowed(t, body.date, slot_time):
            raise HTTPException(400, "This tutor isn't available at that time. Pick another slot.")
        if await find_overlapping_booking(t["id"], body.date, slot_time, body.duration_minutes):
            raise HTTPException(409, "That time overlaps another session. Please pick another time.")
    booking = {
        "id": str(uuid.uuid4()),
        "parent_id": u["id"], "parent_name": u["name"],
        "tutor_id": t["id"], "tutor_name": t["name"],
        "date": body.date, "time": slot_time, "timezone": tz,
        "duration_minutes": body.duration_minutes, "language": body.language,
        "amount_cents": base_amount + fee, "platform_fee_cents": fee,  # amount = what the parent pays
        "currency": t.get("currency", "usd"),
        "payment_status": "pending", "stripe_payment_intent_id": None, "client_secret": None,
        "notes": body.notes or "", "is_au_pair": au_pair, "lessons_count": lessons,
        "distance_miles": distance, "remote": remote and not au_pair,
        "housing_offered": (body.housing_offered or "").strip() if au_pair else "",
        "tutor_response": "pending",  # the tutor accepts or declines once it's paid
        "reschedule_count": 0,
        "created_at": now_iso(),
    }
    await attach_payment_intent(booking, "booking")
    await insert_booking(booking)
    return Booking(**booking)


async def mark_paid(b: dict) -> dict:
    """Shared by the mock confirmation and the Stripe webhook. Idempotent."""
    if b["payment_status"] == "paid":
        return b
    paid_at = now_utc()
    update: dict = {"payment_status": "paid", "paid_at": paid_at.isoformat()}
    if b.get("tutor_response") == "pending":
        deadline = paid_at + timedelta(hours=TUTOR_RESPONSE_HOURS)
        start = booking_start_utc(b)
        if start and start < deadline:
            deadline = max(paid_at + timedelta(minutes=30), start - timedelta(minutes=30))
        update["respond_by"] = deadline.isoformat()
    res = await db.bookings.update_one({"id": b["id"], "payment_status": {"$ne": "paid"}}, {"$set": update})
    b = {**b, **update}
    if res.modified_count == 0:
        return b
    await credit_platform_fee(b)
    tutor_uid = await tutor_user_id(b["tutor_id"])
    when = f"{b['date']} at {b['time']}"
    if b.get("tutor_response") == "pending":
        if tutor_uid:
            await push_notification(tutor_uid, "booking", "New booking request",
                                    f"{b['parent_name']} booked {when}. Accept or decline in the app.", {"booking_id": b["id"]})
        await push_notification(b["parent_id"], "booking", "Booking requested",
                                f"Paid — waiting for {b['tutor_name']} to confirm {when}.", {"booking_id": b["id"]})
    else:
        if tutor_uid:
            await push_notification(tutor_uid, "booking", "New booking confirmed", f"{b['parent_name']} booked {when}", {"booking_id": b["id"]})
        await push_notification(b["parent_id"], "booking", "Booking confirmed", f"You're set with {b['tutor_name']} on {b['date']}", {"booking_id": b["id"]})
    return b


@router.post("/bookings/{booking_id}/confirm-mock", response_model=Booking)
async def confirm_mock(booking_id: str, u: dict = Depends(current_user)):
    """MOCKED payment confirmation — for MVP dev/preview only.

    Gated by env `ENABLE_MOCK_CONFIRM`. In production this MUST be `false` and
    `payment_status` should only be flipped by the signed Stripe webhook."""
    if os.getenv("ENABLE_MOCK_CONFIRM", "true").lower() != "true":
        raise HTTPException(410, "Mock payment confirmation is disabled in this environment.")
    b = await db.bookings.find_one({"id": booking_id}, {"_id": 0})
    if not b:
        raise HTTPException(404, "Booking not found")
    if b["parent_id"] != u["id"]:
        raise HTTPException(403, "Not your booking")
    if b["payment_status"] in ("canceled", "failed"):
        raise HTTPException(400, "This booking was cancelled. Please book again.")
    return Booking(**await mark_paid(b))


@router.get("/bookings/me", response_model=List[Booking])
async def my_bookings(u: dict = Depends(current_user)):
    if u["role"] == "parent":
        q = {"parent_id": u["id"]}
    elif u["role"] == "tutor":
        q = {"tutor_id": await tutor_profile_id(u["id"]) or "__none__"}
    else:
        return []
    docs = await db.bookings.find(q, {"_id": 0}).sort("created_at", -1).to_list(200)
    return [Booking(**d) for d in docs]


@router.get("/bookings/{booking_id}", response_model=Booking)
async def get_booking(booking_id: str, u: dict = Depends(current_user)):
    b, _ = await _load_for(booking_id, u)
    return Booking(**b)


@router.get("/bookings/{booking_id}/cancel-preview")
async def cancel_preview(booking_id: str, u: dict = Depends(current_user)):
    """What cancelling now would mean, so the app can show it before the person confirms."""
    b, side = await _load_for(booking_id, u)
    refund = refund_policy(b, side)
    return {"refund_cents": refund, "paid": b["payment_status"] == "paid", "policy_hours": CANCEL_FULL_REFUND_HOURS}


@router.post("/bookings/{booking_id}/cancel", response_model=Booking)
async def cancel(booking_id: str, body: Optional[CancelRequest] = None, u: dict = Depends(current_user)):
    b, side = await _load_for(booking_id, u)
    if b["payment_status"] == "canceled":
        raise HTTPException(400, "This booking is already cancelled.")
    start = booking_start_utc(b)
    if start and start + timedelta(minutes=int(b.get("duration_minutes") or 60)) < now_utc():
        raise HTTPException(400, "This session has already taken place.")
    return Booking(**await cancel_booking(b, by_role=side, reason=(body.reason if body else "") or ""))


@router.post("/bookings/{booking_id}/respond", response_model=Booking)
async def respond(booking_id: str, body: RespondRequest, u: dict = Depends(current_user)):
    b, side = await _load_for(booking_id, u)
    if side != "tutor":
        raise HTTPException(403, "Only the tutor can accept or decline")
    if b.get("tutor_response", "accepted") != "pending" or b["payment_status"] == "canceled":
        raise HTTPException(400, "This booking was already answered.")
    if not body.accept:
        b = await cancel_booking(b, by_role="tutor", reason=body.note or "Declined by tutor")
        return Booking(**b)
    res = await db.bookings.update_one({"id": b["id"], "tutor_response": "pending"}, {"$set": {"tutor_response": "accepted", "accepted_at": now_iso()}})
    if res.modified_count == 0:
        raise HTTPException(400, "This booking was already answered.")
    b["tutor_response"] = "accepted"
    msg = f"{b['tutor_name']} confirmed {b['date']} at {b['time']}."
    if body.note:
        msg += f" “{body.note.strip()[:120]}”"
    await push_notification(b["parent_id"], "booking", "Booking confirmed", msg, {"booking_id": b["id"]})
    return Booking(**b)


@router.post("/bookings/{booking_id}/reschedule", response_model=Booking)
async def reschedule(booking_id: str, body: RescheduleRequest, u: dict = Depends(current_user)):
    b, side = await _load_for(booking_id, u)
    if side == "admin":
        raise HTTPException(403, "Only the family or the tutor can reschedule")
    if b["payment_status"] in ("canceled", "failed"):
        raise HTTPException(400, "This booking was cancelled.")
    start = booking_start_utc(b)
    if start and start - now_utc() < timedelta(hours=RESCHEDULE_MIN_HOURS):
        raise HTTPException(400, f"Sessions can be moved up to {RESCHEDULE_MIN_HOURS} hours before they start. Message the other side instead.")
    t = await db.tutors.find_one({"id": b["tutor_id"]}, {"_id": 0})
    if not t:
        raise HTTPException(404, "Tutor not found")
    new_time = _normalize_slot(body.time)
    tz = b.get("timezone") or t.get("timezone")
    reject_past_slot(body.date, new_time, tz)
    if not b.get("is_au_pair"):
        if side == "parent" and not is_slot_allowed(t, body.date, new_time):
            raise HTTPException(400, "The tutor isn't available at that time. Pick another slot.")
        if await find_overlapping_booking(t["id"], body.date, new_time, b["duration_minutes"], exclude_booking_id=b["id"]):
            raise HTTPException(409, "That time overlaps another session. Please pick another time.")
    update = {
        "date": body.date, "time": new_time, "timezone": tz,
        "reschedule_count": int(b.get("reschedule_count") or 0) + 1, "updated_at": now_iso(),
    }
    if not b.get("is_au_pair"):
        update["slot_key"] = slot_key(t["id"], body.date, new_time)
    try:
        await db.bookings.update_one({"id": b["id"]}, {
            "$set": update,
            "$push": {"reschedules": {"from_date": b["date"], "from_time": b["time"], "by": side, "at": now_iso()}},
        })
    except DuplicateKeyError:
        raise HTTPException(409, "That slot was just booked by someone else. Please pick another time.")
    b.update(update)
    who = b["parent_name"] if side == "parent" else b["tutor_name"]
    other = await tutor_user_id(b["tutor_id"]) if side == "parent" else b["parent_id"]
    if other:
        await push_notification(other, "booking", "Session moved", f"{who} moved your session to {body.date} at {new_time}.", {"booking_id": b["id"]})
    b.pop("slot_key", None)
    return Booking(**b)


@router.post("/stripe/webhook")
async def stripe_webhook(request: Request, stripe_signature: str = Header(None, alias="Stripe-Signature")):
    payload = await request.body()
    secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "").strip()
    if not secret:
        raise HTTPException(503, "Webhook not configured")
    if not stripe_signature:
        raise HTTPException(400, "Missing signature")
    try:
        event = stripe.Webhook.construct_event(payload, stripe_signature, secret)
    except Exception as e:
        raise HTTPException(400, f"Invalid webhook: {e}")
    intent_id = event["data"]["object"].get("id")
    status_map = {
        "payment_intent.succeeded": "paid",
        "payment_intent.payment_failed": "failed",
        "payment_intent.canceled": "canceled",
    }
    new_status = status_map.get(event["type"])
    if new_status and intent_id:
        b = await db.bookings.find_one({"stripe_payment_intent_id": intent_id}, {"_id": 0})
        if b and new_status == "paid":
            await mark_paid(b)
        elif b and b["payment_status"] != "paid":  # a late failure event never un-pays a booking
            await db.bookings.update_one({"id": b["id"], "payment_status": {"$ne": "paid"}},
                                         {"$set": {"payment_status": new_status}, "$unset": {"slot_key": ""}})
    return {"received": True}
