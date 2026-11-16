"""User blocking: permanent, mutual hiding. Reasons are visible to admins only."""
from datetime import datetime, timezone
from html import escape
from typing import Literal, Optional
import asyncio
import logging
import os
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field

from email_service import send_email
from server import db, current_user, require_admin, blocked_between, push_notification, email_fingerprint

router = APIRouter()
logger = logging.getLogger(__name__)

AUTO_SUSPEND_THRESHOLD = 3  # distinct people blocking someone -> paused for admin review
DEFAULT_ALERT_EMAIL = "copperstone17@gmail.com"
REASON_LABEL = {
    "spam": "Spam", "harassment": "Harassment or bullying", "inappropriate": "Inappropriate content or behaviour",
    "safety": "Child safety concern", "fake": "Fake profile or scam", "other": "Something else",
}


async def safety_alert_email() -> str:
    doc = await db.settings.find_one({"key": "safety_alert_email"}, {"_id": 0})
    return (doc or {}).get("value") or os.environ.get("SAFETY_ALERT_EMAIL") or DEFAULT_ALERT_EMAIL


def _person(u: Optional[dict]) -> str:
    if not u:
        return "Unknown user"
    return f"{escape(u.get('name', ''))} ({escape(u.get('role', ''))}, {escape(u.get('email', ''))})"


def _alert_html(title: str, rows: list[tuple[str, str]], note: str) -> str:
    cells = "".join(
        f'<tr><td style="padding:6px 12px 6px 0;color:#6b6260;vertical-align:top;white-space:nowrap">{escape(k)}</td>'
        f'<td style="padding:6px 0;color:#2b2522">{v}</td></tr>' for k, v in rows
    )
    return (
        '<table role="presentation" width="100%" style="background:#f6efe3"><tr><td style="padding:24px;font-family:Arial,sans-serif">'
        f'<h2 style="margin:0 0 12px;color:#c4561a">{escape(title)}</h2>'
        f'<table role="presentation" style="font-size:14px">{cells}</table>'
        f'<p style="font-size:14px;color:#2b2522">{escape(note)}</p>'
        '<p style="font-size:12px;color:#888">Sent by Babybabel safety monitoring. Review it on the Admin page in the app.</p>'
        '</td></tr></table>'
    )


async def _notify_admin(subject: str, html: str) -> None:
    """Send now; if the provider refuses (e.g. burst rate limit), park it in an outbox."""
    if not await send_email(to=await safety_alert_email(), subject=subject, html=html):
        await db.email_outbox.insert_one({
            "id": str(uuid.uuid4()), "subject": subject, "html": html, "attempts": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })


async def email_outbox_worker() -> None:
    """Retry parked alerts every minute (gives up after 30 attempts)."""
    while True:
        await asyncio.sleep(60)
        try:
            for m in await db.email_outbox.find({"attempts": {"$lt": 30}}, {"_id": 0}).sort("created_at", 1).to_list(20):
                if await send_email(to=await safety_alert_email(), subject=m["subject"], html=m["html"]):
                    await db.email_outbox.delete_one({"id": m["id"]})
                else:
                    await db.email_outbox.update_one({"id": m["id"]}, {"$inc": {"attempts": 1}})
                    break  # provider still refusing — try again next cycle
                await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"Email outbox error: {e}")


async def _maybe_auto_suspend(blocked_id: str, bg: BackgroundTasks) -> bool:
    target = await db.users.find_one({"id": blocked_id}, {"_id": 0})
    if not target or target.get("suspended") or target.get("is_admin"):
        return False
    q: dict = {"blocked_id": blocked_id}
    if target.get("reinstated_at"):  # only count blocks since the admin last cleared them
        q["created_at"] = {"$gt": target["reinstated_at"]}
    blockers = await db.blocks.distinct("blocker_id", q)
    if len(blockers) < AUTO_SUSPEND_THRESHOLD:
        return False
    now = datetime.now(timezone.utc).isoformat()
    reason = f"Blocked by {len(blockers)} different people"
    await db.users.update_one({"id": blocked_id}, {"$set": {"suspended": True, "suspended_at": now, "suspended_reason": reason}})
    await db.tutors.update_one({"user_id": blocked_id}, {"$set": {"suspended": True}})
    bg.add_task(_notify_admin, f"Account paused for review: {target.get('name', '')}"[:120], _alert_html(
        "Account automatically paused", [("Account", _person(target)), ("Why", escape(reason)), ("When", escape(now[:16].replace("T", " ")) + " UTC")],
        "They can't sign in or appear in search until you reinstate them from the Admin page.",
    ))
    return True

BlockReason = Literal["spam", "harassment", "inappropriate", "safety", "fake", "other"]


class BlockCreate(BaseModel):
    user_id: str
    reason: BlockReason
    details: Optional[str] = Field(default="", max_length=1000)


@router.post("/blocks")
async def block_user(body: BlockCreate, bg: BackgroundTasks, u: dict = Depends(current_user)):
    if body.user_id == u["id"]:
        raise HTTPException(400, "You can't block yourself")
    target = await db.users.find_one({"id": body.user_id}, {"_id": 0, "password_hash": 0})
    if not target:
        raise HTTPException(404, "User not found")
    if target.get("is_admin"):
        raise HTTPException(400, "The Babybabel team can't be blocked. Contact support instead.")
    details = (body.details or "").strip()
    if body.reason == "other" and len(details) < 10:
        raise HTTPException(422, "Please describe what happened (at least 10 characters)")
    if await db.blocks.find_one({"blocker_id": u["id"], "blocked_id": body.user_id}, {"_id": 1}):
        raise HTTPException(409, "You've already blocked this person")
    await db.blocks.insert_one({
        "id": str(uuid.uuid4()),
        "blocker_id": u["id"],
        "blocked_id": body.user_id,
        "reason": body.reason,
        "details": details,
        "blocked_email_fp": email_fingerprint(target["email"]),
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    if body.reason == "safety":
        bg.add_task(_notify_admin, f"Child safety block: {target.get('name', '')}"[:120], _alert_html(
            "Child safety concern reported",
            [("Reported by", _person(u)), ("About", _person(target)),
             ("Details", escape(details) or "<em>No details given</em>")],
            "The two accounts are now blocked from each other. Please review and act quickly.",
        ))
    await _maybe_auto_suspend(body.user_id, bg)
    return {"ok": True}


@router.get("/blocks/status/{user_id}")
async def block_status(user_id: str, u: dict = Depends(current_user)):
    """Whether two users are blocked — never reveals which side blocked."""
    return {"blocked": await blocked_between(u["id"], user_id)}


@router.get("/admin/blocks")
async def admin_list_blocks(_: dict = Depends(require_admin)):
    docs = await db.blocks.find({}, {"_id": 0}).sort("created_at", -1).to_list(500)
    ids = {d["blocker_id"] for d in docs} | {d["blocked_id"] for d in docs}
    users = {x["id"]: x for x in await db.users.find(
        {"id": {"$in": list(ids)}}, {"_id": 0, "id": 1, "name": 1, "email": 1, "role": 1}
    ).to_list(len(ids) or 1)}
    counts: dict = {}
    for d in docs:
        counts[d["blocked_id"]] = counts.get(d["blocked_id"], 0) + 1
    for d in docs:
        d["blocker"] = users.get(d["blocker_id"])
        d["blocked"] = users.get(d["blocked_id"])
        d["times_blocked"] = counts[d["blocked_id"]]
    return docs


# ---- Admin: paused accounts + alert settings ----
@router.get("/admin/suspended")
async def admin_suspended(_: dict = Depends(require_admin)):
    users = await db.users.find({"suspended": True}, {"_id": 0, "id": 1, "name": 1, "email": 1, "role": 1, "suspended_at": 1, "suspended_reason": 1}).sort("suspended_at", -1).to_list(200)
    for x in users:
        x["blocked_by"] = len(await db.blocks.distinct("blocker_id", {"blocked_id": x["id"]}))
    return users


@router.post("/admin/users/{user_id}/reinstate")
async def admin_reinstate(user_id: str, _: dict = Depends(require_admin)):
    u = await db.users.find_one({"id": user_id, "suspended": True}, {"_id": 0, "id": 1})
    if not u:
        raise HTTPException(404, "No paused account with that id")
    now = datetime.now(timezone.utc).isoformat()
    await db.users.update_one({"id": user_id}, {"$set": {"suspended": False, "reinstated_at": now}, "$unset": {"suspended_reason": ""}})
    await db.tutors.update_one({"user_id": user_id}, {"$set": {"suspended": False}})
    await push_notification(user_id, "account", "Your account is active again", "Thanks for your patience while we reviewed your account.")
    return {"ok": True}


class AlertEmailBody(BaseModel):
    email: EmailStr


@router.get("/admin/settings/safety-email")
async def get_alert_email(_: dict = Depends(require_admin)):
    return {"email": await safety_alert_email()}


@router.put("/admin/settings/safety-email")
async def set_alert_email(body: AlertEmailBody, _: dict = Depends(require_admin)):
    email = str(body.email).strip().lower()
    await db.settings.update_one({"key": "safety_alert_email"}, {"$set": {"key": "safety_alert_email", "value": email}}, upsert=True)
    return {"email": email}
