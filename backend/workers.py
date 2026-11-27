"""Background maintenance + time-based notifications.

Runs every minute inside the API process. Everything here is idempotent, so running it on
several instances at once is safe (just redundant).
"""
import asyncio
from datetime import datetime, timedelta

from starlette.concurrency import run_in_threadpool

import storage
from booking_service import cancel_booking
from reminders import REMINDER_LOG_RETENTION_DAYS, send_session_reminders
MESSAGE_FLAG_RETENTION_DAYS = 365

from core import (  # noqa: E402
    EVENT_RETENTION_DAYS, NOTIFICATION_RETENTION_DAYS, ORPHAN_UPLOAD_HOURS, PENDING_PAYMENT_MINUTES,
    PUSH_TOKEN_RETENTION_DAYS, booking_end_utc, booking_start_utc, db, logger, notify_once, now_utc, zone,
    tutor_has_completed_session, tutor_user_id,
)


async def generate_for_user(u: dict) -> None:
    """Morning-of, coming-up and post-session review notifications for one user's sessions."""
    now = now_utc()
    if u["role"] == "tutor":
        if not await db.w9_forms.find_one({"tutor_user_id": u["id"]}, {"_id": 1}):
            if await tutor_has_completed_session(u["id"]):
                await notify_once(u["id"], "w9:required", "Complete your W-9 (US tax form)",
                                  "You've completed your first session — file a W-9 so we can pay you.")
        return
    if u["role"] != "parent":
        return
    lo = (now - timedelta(days=8)).date().isoformat()
    hi = (now + timedelta(days=2)).date().isoformat()
    bookings = await db.bookings.find(
        {"parent_id": u["id"], "payment_status": "paid", "date": {"$gte": lo, "$lte": hi}}, {"_id": 0},
    ).to_list(200)
    for b in bookings:
        await _booking_notifications(b, now)


async def _booking_notifications(b: dict, now: datetime) -> None:
    start, end = booking_start_utc(b), booking_end_utc(b)
    if not start or not end:
        return
    confirmed = b.get("tutor_response", "accepted") == "accepted"
    # A rescheduled session gets fresh reminders: morning:<id>:r1, reminder:<id>:r1, …
    moves = int(b.get("reschedule_count") or 0)
    tag = b["id"] if moves == 0 else f"{b['id']}:r{moves}"
    minutes_to_start = (start - now).total_seconds() / 60
    data = {"booking_id": b["id"]}
    if confirmed:
        await send_session_reminders(b, start, tag)  # email / text, day before and hour before
        # Morning-of: the session is today in its own time zone and still upcoming.
        local_today = now.astimezone(zone(b.get("timezone"))).date()
        if start.astimezone(zone(b.get("timezone"))).date() == local_today and 10 < minutes_to_start < 24 * 60:
            await notify_once(b["parent_id"], f"morning:{tag}", f"Session today at {b['time']}",
                              f"{b['tutor_name']} · {b['language']} · tap to get ready", data)
        if -30 < minutes_to_start < 120:
            await notify_once(b["parent_id"], f"reminder:{tag}", "Your session is coming up soon",
                              f"{b['tutor_name']} at {b['time']} · {b['language']}", data)
            tutor_uid = await tutor_user_id(b["tutor_id"])
            if tutor_uid:
                await notify_once(tutor_uid, f"reminder:{tag}", "Your session is coming up soon",
                                  f"{b['parent_name']} at {b['time']} · {b['language']}", data)
    # Review request 30+ minutes after the session ended.
    if end < now - timedelta(minutes=30) and not await db.reviews.find_one({"booking_id": b["id"]}, {"_id": 1}):
        await notify_once(b["parent_id"], f"review:{b['id']}", "How was your session?",
                          f"Rate {b['tutor_name']} and help other families.", data)


async def expire_unpaid_bookings() -> int:
    """Unpaid bookings hold the slot for PENDING_PAYMENT_MINUTES, then release it."""
    cutoff = (now_utc() - timedelta(minutes=PENDING_PAYMENT_MINUTES)).isoformat()
    n = 0
    async for b in db.bookings.find({"payment_status": "pending", "created_at": {"$lt": cutoff}}, {"_id": 0}):
        await cancel_booking(b, by_role="system", reason="Payment wasn't completed in time", notify=False)
        n += 1
    return n


async def expire_unanswered_requests() -> int:
    """A paid request the tutor didn't answer in time is cancelled with a full refund."""
    now = now_utc().isoformat()
    n = 0
    async for b in db.bookings.find({"payment_status": "paid", "tutor_response": "pending", "respond_by": {"$lt": now}}, {"_id": 0}):
        await cancel_booking(b, by_role="system", reason="The tutor didn't respond in time")
        n += 1
    return n


async def purge_expired_w9s() -> int:
    res = await db.w9_forms.delete_many({"retain_until": {"$lt": now_utc().isoformat()}})
    return res.deleted_count


async def send_due_reminders() -> None:
    """Reminders for sessions in the next day or the last week, for users who aren't polling."""
    now = now_utc()
    lo = (now - timedelta(days=8)).date().isoformat()
    hi = (now + timedelta(days=2)).date().isoformat()
    async for b in db.bookings.find({"payment_status": "paid", "date": {"$gte": lo, "$lte": hi}}, {"_id": 0}):
        await _booking_notifications(b, now)


# ---- Data minimisation: delete what's no longer needed ----
def _ago(**kw) -> str:
    return (now_utc() - timedelta(**kw)).isoformat()


async def purge_short_lived_records() -> dict:
    """Expired one-time codes, old notifications and usage stats, dead push tokens and
    emails that could never be delivered."""
    now = now_utc().isoformat()
    counts = {
        "auth_codes": (await db.auth_codes.delete_many({"expires_at": {"$lt": now}})).deleted_count,
        "notifications": (await db.notifications.delete_many({"at": {"$lt": _ago(days=NOTIFICATION_RETENTION_DAYS)}})).deleted_count,
        "events": (await db.events.delete_many({"at": {"$lt": _ago(days=EVENT_RETENTION_DAYS)}})).deleted_count,
        "push_tokens": (await db.push_tokens.delete_many({"updated_at": {"$lt": _ago(days=PUSH_TOKEN_RETENTION_DAYS)}})).deleted_count,
        "email_outbox": (await db.email_outbox.delete_many({"attempts": {"$gte": 30}})).deleted_count,
        "reminder_log": (await db.reminder_log.delete_many({"at": {"$lt": _ago(days=REMINDER_LOG_RETENTION_DAYS)}})).deleted_count,
        # Reviewed message-safety items are kept for a while in case a pattern emerges, then deleted.
        "message_flags": (await db.message_flags.delete_many(
            {"status": "resolved", "resolved_at": {"$lt": _ago(days=MESSAGE_FLAG_RETENTION_DAYS)}})).deleted_count,
    }
    if any(counts.values()):
        logger.info(f"data clean-up: {counts}")
    return counts


async def _referenced_upload_paths() -> set:
    """Every stored file something still points at."""
    refs: set = set()
    async for u in db.users.find({"avatar_url": {"$nin": [None, ""]}}, {"_id": 0, "avatar_url": 1}):
        refs.add(u["avatar_url"])
    tutor_fields = ("avatar_url", "hero_image_url", "accreditation_photo_url", "accreditation_document_url",
                    "id_document_url", "background_check_url")
    async for t in db.tutors.find({}, {"_id": 0, **{f: 1 for f in tutor_fields}, "accreditation_urls": 1}):
        refs.update(t.get(f) for f in tutor_fields if t.get(f))
        refs.update(t.get("accreditation_urls") or [])
    async for p in db.parents.find({}, {"_id": 0, "avatar_url": 1, "children.avatar_url": 1}):
        if p.get("avatar_url"):
            refs.add(p["avatar_url"])
        refs.update(c.get("avatar_url") for c in p.get("children") or [] if c.get("avatar_url"))
    async for post in db.posts.find({}, {"_id": 0, "cover_image_url": 1, "image_urls": 1}):
        if post.get("cover_image_url"):
            refs.add(post["cover_image_url"])
        refs.update(post.get("image_urls") or [])
    return {r.split("/api/files/", 1)[-1] for r in refs if isinstance(r, str)}


async def purge_orphan_uploads() -> int:
    """Files nobody references any more (a replaced photo, an abandoned upload) are deleted
    once they're older than ORPHAN_UPLOAD_HOURS — enough time to finish saving a form."""
    cutoff = _ago(hours=ORPHAN_UPLOAD_HOURS)
    candidates = await db.uploads.find({"created_at": {"$lt": cutoff}}, {"_id": 0, "path": 1}).to_list(5000)
    if not candidates:
        return 0
    refs = await _referenced_upload_paths()
    removed = 0
    for c in candidates:
        if c["path"] in refs:
            continue
        await run_in_threadpool(storage.delete_object, c["path"])
        await db.uploads.delete_one({"path": c["path"]})
        removed += 1
    if removed:
        logger.info(f"data clean-up: removed {removed} unused uploaded file(s)")
    return removed


_last_hourly = 0.0


async def hourly_jobs() -> None:
    global _last_hourly
    now = now_utc().timestamp()
    if now - _last_hourly < 3600:
        return
    _last_hourly = now
    await purge_short_lived_records()
    await purge_orphan_uploads()
    await purge_expired_w9s()


async def run_once() -> None:
    for job in (expire_unpaid_bookings, expire_unanswered_requests, send_due_reminders, hourly_jobs):
        try:
            await job()
        except Exception as e:
            logger.error(f"maintenance job {job.__name__} failed: {e}")


async def maintenance_loop(interval_seconds: int = 60) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        await run_once()
