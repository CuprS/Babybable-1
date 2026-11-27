"""Session reminders by email (on by default) and text message (opt-in, confirmed number only).

Sent the day before (about 24 hours ahead) and about an hour before each confirmed, paid session,
to both the family and the tutor. Each reminder is recorded in `reminder_log`, so the worker can
run every minute, on several servers, without sending anything twice. A moved session gets a fresh
set of reminders.
"""
from datetime import datetime, timedelta
from html import escape
from typing import Optional

from core import PUBLIC_WEB_URL, db, logger, now_iso, now_utc, tutor_user_id, zone
from email_service import send_email
from sms_service import send_sms, sms_available

DAY_WINDOW = (120, 24 * 60)   # minutes before the start: the day-before reminder goes out in here
HOUR_WINDOW = (0, 75)         # …and the one-hour reminder in here
JUST_BOOKED_MINUTES = {"day": 120, "hour": 15}  # don't remind people who booked moments ago
REMINDER_LOG_RETENTION_DAYS = 30


def when_text(b: dict, start: datetime, viewer_tz: Optional[str]) -> str:
    """'Saturday 6 December at 10:00 (Madrid time)', plus the viewer's own time if it differs."""
    tz = b.get("timezone") or "UTC"
    local = start.astimezone(zone(tz))
    city = tz.split("/")[-1].replace("_", " ")
    text = f"{local:%A} {local.day} {local:%B} at {local:%H:%M} ({city} time)"
    if viewer_tz and viewer_tz != tz:
        mine = start.astimezone(zone(viewer_tz))
        text += f" — {mine:%H:%M} where you are"
    return text


def booking_link(booking_id: str) -> Optional[str]:
    # Email links must be https (see email_service's guardrail), so local http setups get none.
    return f"{PUBLIC_WEB_URL}/booking-detail/{booking_id}" if PUBLIC_WEB_URL.startswith("https://") else None


def reminder_email(name: str, other: str, b: dict, when: str, which: str) -> tuple[str, str]:
    soon = which == "hour"
    subject = f"Starting soon: your {b['language']} session with {other}" if soon else \
        f"Reminder: your {b['language']} session with {other} is coming up"
    where = "Online" if b.get("remote") else "In person"
    link = booking_link(b["id"])
    button = (f'<p style="margin:20px 0"><a href="{escape(link)}" style="background:#B83A23;color:#ffffff;'
              'padding:12px 20px;border-radius:999px;text-decoration:none;font-weight:bold;font-size:16px">'
              'See the booking</a></p>') if link else ""
    html = (
        '<table role="presentation" width="100%" style="background:#FAF8F5"><tr>'
        '<td style="padding:24px;font-family:Arial,sans-serif;color:#2C2421;font-size:16px;line-height:1.5">'
        f'<h2 style="margin:0 0 12px;color:#B83A23">{"Your session starts in about an hour" if soon else "Your session is coming up"}</h2>'
        f'<p>Hi {escape(name)},</p>'
        f'<p>This is a reminder of your <strong>{escape(b["language"])}</strong> session with '
        f'<strong>{escape(other)}</strong>.</p>'
        '<table role="presentation" style="font-size:16px;margin:12px 0">'
        f'<tr><td style="padding:4px 16px 4px 0;color:#5A4C46">When</td><td>{escape(when)}</td></tr>'
        f'<tr><td style="padding:4px 16px 4px 0;color:#5A4C46">Length</td><td>{int(b.get("duration_minutes") or 60)} minutes</td></tr>'
        f'<tr><td style="padding:4px 16px 4px 0;color:#5A4C46">Where</td><td>{where}</td></tr>'
        '</table>'
        f'{button}'
        '<p style="font-size:14px;color:#5A4C46">Need to change it? Open the booking in the Babybabel app. '
        'For everyone\'s safety, keep messages and payments on Babybabel.</p>'
        '<p style="font-size:13px;color:#5A4C46">You can turn these emails off in your Babybabel profile, '
        'under Session reminders.</p>'
        '</td></tr></table>'
    )
    return subject, html


def reminder_text(other: str, b: dict, when: str, which: str) -> str:
    lead = "Babybabel: your session starts in about an hour" if which == "hour" else "Babybabel reminder: you have a session coming up"
    return f"{lead} — {b['language']} with {other}, {when}. Reply STOP to stop texts."


async def _claim(key: str, user_id: str) -> bool:
    """True the first time this reminder is claimed; False if it was already sent."""
    res = await db.reminder_log.update_one(
        {"key": key}, {"$setOnInsert": {"key": key, "user_id": user_id, "at": now_iso()}}, upsert=True,
    )
    return res.upserted_id is not None


async def _remind(user_id: str, other: str, b: dict, start: datetime, which: str, tag: str) -> None:
    user = await db.users.find_one({"id": user_id}, {"_id": 0})
    if not user or user.get("suspended"):
        return
    when = when_text(b, start, user.get("timezone"))
    if user.get("reminder_email", True) and user.get("email") and await _claim(f"email:{which}:{tag}:{user_id}", user_id):
        subject, html = reminder_email(user.get("name", "there").split(" ")[0], other, b, when, which)
        try:
            await send_email(to=user["email"], subject=subject, html=html)
        except ValueError as e:
            logger.error(f"reminder email rejected by guardrail: {e}")
    if (user.get("reminder_sms") and user.get("phone") and user.get("phone_verified") and sms_available()
            and await _claim(f"sms:{which}:{tag}:{user_id}", user_id)):
        await send_sms(user["phone"], reminder_text(other, b, when, which))


async def send_session_reminders(b: dict, start: datetime, tag: str) -> None:
    """Called by the worker for each confirmed, paid booking near its start time."""
    now = now_utc()
    minutes_to_start = (start - now).total_seconds() / 60
    which = None
    if HOUR_WINDOW[0] < minutes_to_start <= HOUR_WINDOW[1]:
        which = "hour"
    elif DAY_WINDOW[0] < minutes_to_start <= DAY_WINDOW[1]:
        which = "day"
    if not which:
        return
    booked_at = b.get("paid_at") or b.get("created_at")
    try:
        if booked_at and datetime.fromisoformat(booked_at) > now - timedelta(minutes=JUST_BOOKED_MINUTES[which]):
            return
    except ValueError:
        pass
    await _remind(b["parent_id"], b["tutor_name"], b, start, which, tag)
    tutor_uid = await tutor_user_id(b["tutor_id"])
    if tutor_uid:
        await _remind(tutor_uid, b["parent_name"], b, start, which, tag)
