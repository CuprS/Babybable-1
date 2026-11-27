"""'Add to my calendar' for a booking: an .ics file (Apple Calendar, Outlook and most others) and
a Google Calendar link. Only the people in the booking can get these (see routes/bookings.py)."""
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlencode

from core import booking_end_utc, booking_start_utc
from reminders import booking_link

PRODID = "-//Babybabel//Bookings//EN"


def event_details(b: dict, side: str) -> Optional[dict]:
    start, end = booking_start_utc(b), booking_end_utc(b)
    if not start or not end:
        return None
    other = b["parent_name"] if side == "tutor" else b["tutor_name"]
    title = f"Babybabel: {b['language']} session with {other}"
    where = "Online" if b.get("remote") else "In person"
    link = booking_link(b["id"])
    lines = [f"{b['language']} session with {other} ({where.lower()}).",
             "Booked on Babybabel. To move or cancel it, open the booking in the Babybabel app."]
    if link:
        lines.append(link)
    return {"title": title, "details": "\n".join(lines), "location": where, "start": start, "end": end, "link": link}


def _utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def google_calendar_url(ev: dict) -> str:
    q = {"action": "TEMPLATE", "text": ev["title"], "dates": f"{_utc(ev['start'])}/{_utc(ev['end'])}",
         "details": ev["details"], "location": ev["location"]}
    return "https://calendar.google.com/calendar/render?" + urlencode(q)


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r", "").replace("\n", "\\n")


def _fold(line: str) -> str:
    """iCalendar lines are at most 75 octets; longer ones continue on lines starting with a space."""
    out, cur = [], ""
    for ch in line:
        if len((cur + ch).encode("utf-8")) > 74:
            out.append(cur)
            cur = " "
        cur += ch
    out.append(cur)
    return "\r\n".join(out)


def ics_for(b: dict, ev: dict) -> str:
    canceled = b.get("payment_status") == "canceled"
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:{PRODID}", "CALSCALE:GREGORIAN",
        f"METHOD:{'CANCEL' if canceled else 'PUBLISH'}",
        "BEGIN:VEVENT",
        f"UID:{b['id']}@babybabel",
        # A moved session updates the same calendar entry instead of adding a second one.
        f"SEQUENCE:{int(b.get('reschedule_count') or 0) + (1 if canceled else 0)}",
        f"DTSTAMP:{_utc(datetime.now(timezone.utc))}",
        f"DTSTART:{_utc(ev['start'])}", f"DTEND:{_utc(ev['end'])}",
        f"SUMMARY:{_escape(ev['title'])}", f"DESCRIPTION:{_escape(ev['details'])}",
        f"LOCATION:{_escape(ev['location'])}",
        f"STATUS:{'CANCELLED' if canceled else 'CONFIRMED'}",
    ]
    if ev.get("link"):
        lines.append(f"URL:{ev['link']}")
    if not canceled:
        lines += ["BEGIN:VALARM", "ACTION:DISPLAY", "DESCRIPTION:Babybabel session in 1 hour", "TRIGGER:-PT1H", "END:VALARM"]
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(_fold(x) for x in lines) + "\r\n"
