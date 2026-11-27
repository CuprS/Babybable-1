"""Message safety warnings, session reminders (email / text) and 'Add to my calendar'."""
from datetime import datetime, timedelta, timezone

import pytest

import core
import reminders
import workers
from contact_guard import detect_contact_info
from routes import auth as auth_routes
from test_app import insert_booking


# ---- Spotting contact details ----
@pytest.mark.parametrize("text,kind", [
    ("call me 555-123-4567", "phone"), ("+44 7700 900123", "phone"), ("text me 5551234", "phone"),
    ("jane.doe@gmail.com", "email"), ("jane dot doe at gmail dot com", "email"),
    ("I live at 42 Oak Street", "address"), ("Austin, TX 78701", "address"),
    ("pay me on venmo", "payment"), ("send it to $janecash", "payment"), ("pay me directly in cash", "payment"),
    ("message me on whatsapp", "app"), ("see www.example.com", "link"),
])
def test_detects_contact_details(text, kind):
    assert kind in detect_contact_info(text)


@pytest.mark.parametrize("text", [
    "Is Saturday at 10:00 ok?", "The lesson is $40 for 60 minutes", "How about 2026-12-05 at 9:30?",
    "We can do 10:00 - 11:00", "My daughter is 4 and loves songs", "I have 15 years of experience",
    "Book through babybabel.com please",
])
def test_ordinary_messages_pass(text):
    assert detect_contact_info(text) == []


# ---- Chat: warn, then send anyway, label and queue for admins ----
def admin_headers(db_call, make_user):
    admin = make_user()
    db_call(core.db.users.update_one, {"id": admin["user"]["id"]}, {"$set": {"is_admin": True}})
    token = core.make_token(admin["user"]["id"], "parent", admin=True)
    return {"Authorization": f"Bearer {token}"}


def test_contact_details_before_booking_need_confirming(client, make_user, sofia, db_call):
    parent = make_user()
    to_tutor = {"to_user_id": sofia["user"]["id"], "text": "Text me on 512-555-0199 and I'll pay you on Venmo"}
    r = client.post("/api/messages", headers=parent["h"], json=to_tutor)
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["code"] == "contact_warning" and set(detail["kinds"]) == {"phone", "payment"}
    assert not db_call(core.db.messages.find_one, {"from_user_id": parent["user"]["id"]})

    r = client.post("/api/messages", headers=parent["h"], json={**to_tutor, "confirm_share": True})
    assert r.status_code == 200 and set(r.json()["flags"]) == {"phone", "payment"}
    thread = client.get(f"/api/messages/thread/{parent['user']['id']}", headers=sofia["h"]).json()
    assert set(thread[-1]["flags"]) == {"phone", "payment"}  # the tutor sees the safety label too

    admin = admin_headers(db_call, make_user)
    queue = client.get("/api/admin/message-flags", headers=admin).json()
    item = next(f for f in queue["flags"] if f["from_user_id"] == parent["user"]["id"])
    assert item["from_user"]["name"] == parent["user"]["name"] and item["sender_flag_count"] == 1
    assert client.get("/api/admin/message-flags", headers=parent["h"]).status_code == 403
    assert client.post(f"/api/admin/message-flags/{item['id']}/resolve", headers=admin, json={"outcome": "fine"}).status_code == 200
    assert client.post(f"/api/admin/message-flags/{item['id']}/resolve", headers=admin, json={"outcome": "fine"}).status_code == 404


def test_no_warning_once_they_have_a_paid_booking(client, make_user, sofia, db_call):
    parent = make_user()
    insert_booking(db_call, parent, sofia["profile"], datetime.now(timezone.utc) + timedelta(days=3))
    r = client.post("/api/messages", headers=parent["h"], json={"to_user_id": sofia["user"]["id"], "text": "We're at 42 Oak Street"})
    assert r.status_code == 200 and r.json()["flags"] == []


def test_ordinary_message_has_no_flags(client, make_user, sofia):
    parent = make_user()
    r = client.post("/api/messages", headers=parent["h"], json={"to_user_id": sofia["user"]["id"], "text": "Hello! Is Saturday ok?"})
    assert r.status_code == 200 and r.json()["flags"] == []


# ---- Reminders ----
@pytest.fixture
def outbox(monkeypatch):
    sent = {"email": [], "sms": []}

    async def fake_email(*, to, subject, html):
        sent["email"].append((to, subject, html))
        return "id"

    async def fake_sms(to, body):
        sent["sms"].append((to, body))
        return True
    monkeypatch.setattr(reminders, "send_email", fake_email)
    monkeypatch.setattr(reminders, "send_sms", fake_sms)
    monkeypatch.setattr(auth_routes, "send_sms", fake_sms)
    return sent


def test_day_and_hour_reminders_sent_once_to_both(client, make_user, sofia, db_call, outbox):
    parent = make_user()
    old = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    day = insert_booking(db_call, parent, sofia["profile"], datetime.now(timezone.utc) + timedelta(hours=20), paid_at=old)
    db_call(workers.run_once)
    db_call(workers.run_once)  # running again doesn't send twice
    to_parent = [e for e in outbox["email"] if e[0] == parent["email"]]
    assert len(to_parent) == 1 and "coming up" in to_parent[0][1]
    assert any(e[0] == "sofia@babybabel.dev" for e in outbox["email"])

    db_call(core.db.bookings.update_one, {"id": day["id"]}, {"$set": {"payment_status": "canceled"}})
    insert_booking(db_call, parent, sofia["profile"], datetime.now(timezone.utc) + timedelta(minutes=50), paid_at=old)
    db_call(workers.run_once)
    assert any("Starting soon" in e[1] for e in outbox["email"] if e[0] == parent["email"])


def test_no_reminder_right_after_booking_or_when_turned_off(client, make_user, sofia, db_call, outbox):
    parent = make_user()
    insert_booking(db_call, parent, sofia["profile"], datetime.now(timezone.utc) + timedelta(hours=10))  # just booked
    db_call(workers.run_once)
    assert not [e for e in outbox["email"] if e[0] == parent["email"]]

    other = make_user()
    r = client.put("/api/auth/me/reminders", headers=other["h"], json={"email": False})
    assert r.status_code == 200 and r.json()["email"] is False
    old = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    insert_booking(db_call, other, sofia["profile"], datetime.now(timezone.utc) + timedelta(hours=10), paid_at=old)
    db_call(workers.run_once)
    assert not [e for e in outbox["email"] if e[0] == other["email"]]


def test_text_reminders_need_a_confirmed_number(client, make_user, sofia, db_call, outbox, codes, monkeypatch):
    parent = make_user()
    assert client.get("/api/auth/me/reminders", headers=parent["h"]).json() == {
        "email": True, "sms": False, "phone": None, "phone_verified": False, "sms_available": False}
    assert client.post("/api/auth/me/phone", headers=parent["h"], json={"phone": "512 555 0199", "consent": True}).status_code == 503

    monkeypatch.setattr(auth_routes, "sms_available", lambda: True)
    monkeypatch.setattr(reminders, "sms_available", lambda: True)
    assert client.put("/api/auth/me/reminders", headers=parent["h"], json={"sms": True}).status_code == 400
    assert client.post("/api/auth/me/phone", headers=parent["h"], json={"phone": "512 555 0199"}).status_code == 400  # no consent
    assert client.post("/api/auth/me/phone", headers=parent["h"], json={"phone": "12", "consent": True}).status_code == 422
    r = client.post("/api/auth/me/phone", headers=parent["h"], json={"phone": "(512) 555-0199", "consent": True})
    assert r.status_code == 200 and r.json()["phone"] == "•••• 0199"
    to, body = outbox["sms"][-1]
    assert to == "+15125550199"
    code = body.split("code is ")[1][:6]
    assert client.post("/api/auth/me/phone/verify", headers=parent["h"], json={"code": "000000" if code != "000000" else "111111"}).status_code == 400
    r = client.post("/api/auth/me/phone/verify", headers=parent["h"], json={"code": code})
    assert r.status_code == 200 and r.json()["sms"] is True and r.json()["phone_verified"] is True

    old = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    insert_booking(db_call, parent, sofia["profile"], datetime.now(timezone.utc) + timedelta(minutes=45), paid_at=old)
    db_call(workers.run_once)
    assert any(t == "+15125550199" and "STOP" in b for t, b in outbox["sms"])

    r = client.delete("/api/auth/me/phone", headers=parent["h"])
    assert r.status_code == 200 and r.json()["phone"] is None and r.json()["sms"] is False
    doc = db_call(core.db.users.find_one, {"id": parent["user"]["id"]})
    assert "phone" not in doc


# ---- Add to my calendar ----
def test_calendar_file_and_google_link(client, make_user, sofia, db_call):
    parent = make_user()
    start = (datetime.now(timezone.utc) + timedelta(days=3)).replace(hour=15, minute=0, second=0, microsecond=0)
    b = insert_booking(db_call, parent, sofia["profile"], start)
    r = client.get(f"/api/bookings/{b['id']}/calendar", headers=parent["h"])
    assert r.status_code == 200
    data = r.json()
    assert data["google_url"].startswith("https://calendar.google.com/calendar/render?action=TEMPLATE")
    assert start.strftime("%Y%m%dT150000Z") in data["google_url"]

    r = client.get(f"/api/bookings/{b['id']}/calendar.ics", headers=sofia["h"])  # the tutor can too
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/calendar")
    ics = r.text
    assert "BEGIN:VEVENT" in ics and f"UID:{b['id']}@babybabel" in ics and "STATUS:CONFIRMED" in ics
    assert f"DTSTART:{start.strftime('%Y%m%dT150000Z')}" in ics
    assert parent["user"]["name"] in ics.replace("\r\n ", "")
    assert all(len(line.encode()) <= 75 for line in ics.split("\r\n"))

    stranger = make_user()
    assert client.get(f"/api/bookings/{b['id']}/calendar.ics", headers=stranger["h"]).status_code == 403
