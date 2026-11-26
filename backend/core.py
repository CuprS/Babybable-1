"""Shared infrastructure: config, database, auth, storage, time & slot helpers, notifications.

Route modules in routes/ import from here. Nothing in this module registers HTTP routes.
"""
import asyncio
import base64
import binascii
import hashlib
import logging
import math
import os
import secrets
import threading
import time
import uuid
from collections import defaultdict, deque
from datetime import date as date_cls, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import bcrypt
import httpx
import jwt
import requests
from cryptography.fernet import Fernet, MultiFernet, InvalidToken
from dotenv import load_dotenv
from fastapi import Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer
from motor.motor_asyncio import AsyncIOMotorClient

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

# ---- Config ----
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
JWT_SECRET = os.environ["JWT_SECRET"]
if "change-me" in JWT_SECRET or len(JWT_SECRET) < 32:
    raise RuntimeError("JWT_SECRET is a weak/placeholder value — refusing to start")
JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_MINUTES = int(os.environ.get("ACCESS_TOKEN_MINUTES", "10080"))
# Admin sign-ins are short (12 hours by default) and need an emailed code as well as the password.
ADMIN_SESSION_MINUTES = int(os.environ.get("ADMIN_SESSION_MINUTES", "720"))
APP_NAME = os.environ.get("APP_NAME", "babybabel")
# The seeded admin account and the default safety-alert recipient. Set in .env — a personal
# address shouldn't live in source code (the repo is public).
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "").strip().lower()
# Max upload size (bytes). Uploads are read into memory, so keep this modest.
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))
# Public web address of the app (used in emails, sitemap and share pages).
PUBLIC_WEB_URL = os.environ.get("PUBLIC_WEB_URL", "").rstrip("/")
# Off by default so existing flows keep working; set true to require a verified email
# before booking, messaging or publishing.
REQUIRE_EMAIL_VERIFICATION = os.environ.get("REQUIRE_EMAIL_VERIFICATION", "false").lower() == "true"

# Booking policy (hours / minutes)
CANCEL_FULL_REFUND_HOURS = int(os.environ.get("CANCEL_FULL_REFUND_HOURS", "24"))
RESCHEDULE_MIN_HOURS = int(os.environ.get("RESCHEDULE_MIN_HOURS", "24"))
TUTOR_RESPONSE_HOURS = int(os.environ.get("TUTOR_RESPONSE_HOURS", "24"))
PENDING_PAYMENT_MINUTES = int(os.environ.get("PENDING_PAYMENT_MINUTES", "30"))
# US payers must keep W-9s for 4 years after the last return they relate to.
W9_RETENTION_DAYS = int(os.environ.get("W9_RETENTION_DAYS", str(4 * 365)))
# Data minimisation: how long short-lived records are kept before automatic deletion.
NOTIFICATION_RETENTION_DAYS = int(os.environ.get("NOTIFICATION_RETENTION_DAYS", "90"))
EVENT_RETENTION_DAYS = int(os.environ.get("EVENT_RETENTION_DAYS", "90"))
PUSH_TOKEN_RETENTION_DAYS = int(os.environ.get("PUSH_TOKEN_RETENTION_DAYS", "180"))
ORPHAN_UPLOAD_HOURS = int(os.environ.get("ORPHAN_UPLOAD_HOURS", "24"))


# MONGO_URL=memory://data/dev-db.json runs a local, file-backed stand-in (see devdb.py) so the
# app works on a laptop without MongoDB. Anything else is a real MongoDB connection string.
DEV_DATABASE = MONGO_URL.startswith("memory://")
if DEV_DATABASE:
    import devdb

    client = devdb.make_client()
else:
    client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]

logger = logging.getLogger("babybabel")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return now_utc().isoformat()


# ---- Geocoding + distance ----
_geocode_lock = threading.Lock()
_last_geocode_at = 0.0
_geocode_cache: dict = {}


def geocode(city: str) -> Optional[dict]:
    """Free geocoding via Nominatim. 1 req/sec per usage policy."""
    city = (city or "").strip()
    if not city:
        return None
    if city in _geocode_cache:
        return _geocode_cache[city]
    global _last_geocode_at
    try:
        with _geocode_lock:
            wait = 1.0 - (time.time() - _last_geocode_at)
            if wait > 0:
                time.sleep(wait)
            resp = requests.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": city, "format": "json", "limit": 1},
                headers={"User-Agent": f"{APP_NAME}/1.0"},
                timeout=8,
            )
            _last_geocode_at = time.time()
        resp.raise_for_status()
        arr = resp.json()
        if len(_geocode_cache) > 5000:
            _geocode_cache.clear()
        if not arr:
            _geocode_cache[city] = None
            return None
        out = {"latitude": float(arr[0]["lat"]), "longitude": float(arr[0]["lon"])}
        _geocode_cache[city] = out
        return out
    except Exception as e:
        logger.warning(f"geocode({city}) failed: {e}")
        return None


def haversine_miles(a_lat: float, a_lng: float, b_lat: float, b_lng: float) -> float:
    R = 3958.8  # miles
    la1, la2 = math.radians(a_lat), math.radians(b_lat)
    dla = math.radians(b_lat - a_lat)
    dlo = math.radians(b_lng - a_lng)
    h = math.sin(dla / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlo / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


# ---- Rate limiter (in-memory, per-IP — use Redis if you run several workers) ----
_rate_lock = threading.Lock()
_rate_buckets: dict = defaultdict(deque)


def _client_ip(request: Request) -> str:
    """The caller's IP. Our ingress APPENDS the real client IP as the right-most value in
    X-Forwarded-For (left-side values are attacker-controlled)."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            return parts[-1]
    real = request.headers.get("x-real-ip")
    if real:
        return real.strip()
    return request.client.host if request.client else "unknown"


def rate_limit(bucket: str, max_hits: int, per_seconds: int, request: Request, key: str = "", per_ip: bool = True) -> None:
    """Sliding-window rate limit keyed by bucket + IP (+ optional extra key, e.g. an email).
    per_ip=False counts the key across all IPs, so rotating addresses doesn't help an attacker."""
    k = f"{bucket}:{_client_ip(request) if per_ip else '*'}:{key}"
    now = time.time()
    with _rate_lock:
        dq = _rate_buckets[k]
        while dq and now - dq[0] > per_seconds:
            dq.popleft()
        if len(dq) >= max_hits:
            retry = int(per_seconds - (now - dq[0])) + 1
            raise HTTPException(
                status_code=429,
                detail="Too many attempts. Please wait a moment and try again.",
                headers={"Retry-After": str(max(1, retry))},
            )
        dq.append(now)


# ---- Time zones ----
def valid_timezone(name: Optional[str]) -> bool:
    if not name or len(name) > 64:
        return False
    try:
        ZoneInfo(name)
        return True
    except (ZoneInfoNotFoundError, ValueError):
        return False


def zone(name: Optional[str]) -> tzinfo:
    # Plain UTC doesn't need the tz database (absent on Windows without the tzdata package).
    return ZoneInfo(name) if name and name != "UTC" and valid_timezone(name) else timezone.utc


# ---- Slot / weekday helpers ----
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"  # YYYY-MM-DD
TIME_PATTERN = r"^\d{1,2}:\d{2}$"  # H:MM or HH:MM (normalised to HH:MM before storing)
MAX_PRICE_CENTS = 1_000_000  # $10,000 — sanity cap on any single price
ACTIVE_STATUSES = ("pending", "paid")  # bookings that occupy the tutor's calendar


def weekday_key(date_str: str) -> Optional[str]:
    try:
        y, m, d = date_str.split("-")
        return WEEKDAYS[datetime(int(y), int(m), int(d)).weekday()]
    except Exception:
        return None


def _normalize_slot(t: str) -> str:
    """'9:00' -> '09:00'. Returns '' on garbage input."""
    try:
        h, mm = t.split(":")
        h_i, m_i = int(h), int(mm)
        if not (0 <= h_i < 24 and 0 <= m_i < 60):
            return ""
        return f"{h_i:02d}:{m_i:02d}"
    except Exception:
        return ""


def slot_minutes(t: str) -> int:
    n = _normalize_slot(t) or "00:00"
    return int(n[:2]) * 60 + int(n[3:])


def local_start(date_str: str, time_str: str, tz_name: Optional[str]) -> Optional[datetime]:
    """Session start as an aware datetime in the session's time zone."""
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        t = _normalize_slot(time_str)
        if not t:
            return None
        return d.replace(hour=int(t[:2]), minute=int(t[3:]), tzinfo=zone(tz_name))
    except ValueError:
        return None


def booking_start_utc(b: dict) -> Optional[datetime]:
    """Booking times are wall-clock times in the booking's time zone (the tutor's).
    Legacy bookings without one are treated as UTC."""
    s = local_start(b.get("date", ""), b.get("time", ""), b.get("timezone"))
    return s.astimezone(timezone.utc) if s else None


def booking_end_utc(b: dict) -> Optional[datetime]:
    s = booking_start_utc(b)
    return s + timedelta(minutes=int(b.get("duration_minutes") or 60)) if s else None


def reject_past_slot(date_str: str, time_str: str, tz_name: Optional[str]) -> None:
    """422 for malformed dates, 400 for a start time that has already passed in the session's zone."""
    start = local_start(date_str, time_str, tz_name)
    if start is None:
        raise HTTPException(422, "Date must be YYYY-MM-DD and time HH:MM")
    if start < now_utc() - timedelta(minutes=5):
        raise HTTPException(400, "That time has already passed. Pick an upcoming slot.")


def is_slot_allowed(tutor: dict, date: str, time_str: str) -> bool:
    """True if the tutor's weekly_availability allows the slot (or is unset — legacy tutors)."""
    wa = tutor.get("weekly_availability") or {}
    if not wa:
        return True  # legacy tutors haven't set a calendar yet
    wk = weekday_key(date)
    if not wk:
        return True
    slots = wa.get(wk) or []
    if not slots:
        return False
    return _normalize_slot(time_str) in {_normalize_slot(s) for s in slots}


async def find_overlapping_booking(tutor_id: str, date: str, time_str: str, duration_minutes: int = 60,
                                   exclude_booking_id: Optional[str] = None) -> Optional[dict]:
    """Return an active booking whose time range overlaps [time, time+duration) on `date`
    (including one that started the day before and runs past midnight). Au-pair stays are
    long-form arrangements and don't block hourly slots."""
    try:
        day = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        return None
    prev = (day - timedelta(days=1)).isoformat()
    q: dict = {
        "tutor_id": tutor_id,
        "date": {"$in": [date, prev]},
        "payment_status": {"$in": list(ACTIVE_STATUSES)},
        "is_au_pair": {"$ne": True},
    }
    if exclude_booking_id:
        q["id"] = {"$ne": exclude_booking_id}
    start = slot_minutes(time_str)
    end = start + int(duration_minutes or 60)
    async for b in db.bookings.find(q, {"_id": 0}):
        b_start = slot_minutes(b["time"]) - (1440 if b["date"] == prev else 0)
        b_end = b_start + int(b.get("duration_minutes") or 60)
        if b_start < end and start < b_end:
            return b
    return None


async def is_slot_booked(tutor_id: str, date: str, time_str: str, exclude_booking_id: Optional[str] = None,
                         duration_minutes: int = 60) -> bool:
    return bool(await find_overlapping_booking(tutor_id, date, time_str, duration_minutes, exclude_booking_id))


def slot_key(tutor_id: str, date: str, time_str: str) -> str:
    """Unique-indexed key: the database itself refuses two active bookings starting at the
    same tutor/date/time, even if two requests race past the overlap check."""
    return f"{tutor_id}|{date}|{_normalize_slot(time_str)}"


# ---- Platform fee ----
PLATFORM_FEE_BPS = 100  # 1.00% of the base amount, in basis points


def platform_fee_for(base_cents: int) -> int:
    if base_cents <= 0:
        return 0
    return max(1, round(base_cents * PLATFORM_FEE_BPS / 10000))


async def credit_platform_fee(booking: dict) -> None:
    """Idempotently record the platform fee earning for a paid booking."""
    fee = int(booking.get("platform_fee_cents") or 0)
    if fee <= 0:
        return
    if await db.platform_earnings.find_one({"booking_id": booking["id"], "kind": {"$ne": "reversal"}}, {"_id": 1}):
        return  # already credited
    admin = await db.users.find_one({"is_admin": True}, {"_id": 0, "id": 1})
    await db.platform_earnings.insert_one({
        "id": str(uuid.uuid4()), "kind": "fee", "booking_id": booking["id"],
        "admin_user_id": (admin or {}).get("id"),
        "parent_id": booking.get("parent_id"), "tutor_id": booking.get("tutor_id"),
        "amount_cents": fee, "currency": booking.get("currency", "usd"), "at": now_iso(),
    })


async def reverse_platform_fee(booking: dict) -> None:
    """When a paid booking is fully refunded, the platform gives its fee back too."""
    fee = int(booking.get("platform_fee_cents") or 0)
    if fee <= 0 or await db.platform_earnings.find_one({"booking_id": booking["id"], "kind": "reversal"}, {"_id": 1}):
        return
    await db.platform_earnings.insert_one({
        "id": str(uuid.uuid4()), "kind": "reversal", "booking_id": booking["id"],
        "parent_id": booking.get("parent_id"), "tutor_id": booking.get("tutor_id"),
        "amount_cents": -fee, "currency": booking.get("currency", "usd"), "at": now_iso(),
    })


# ---- TIN encryption (Fernet + MultiFernet key rotation) ----
# W9_ENCRYPTION_KEYS: comma-separated Fernet keys. The first encrypts; all decrypt, so you can
# rotate by adding a new key at the front and keeping the old one until records are re-saved.
_W9_KEYS_ENV = os.getenv("W9_ENCRYPTION_KEYS", "").strip()
if _W9_KEYS_ENV:
    _raw_keys = [k.strip() for k in _W9_KEYS_ENV.split(",") if k.strip()]
    _EPHEMERAL_W9_KEY = False
else:
    _raw_keys = [Fernet.generate_key().decode()]
    _EPHEMERAL_W9_KEY = True
    logger.warning(
        "W9_ENCRYPTION_KEYS is not set — generated a one-off in-memory key. "
        "Set W9_ENCRYPTION_KEYS in backend/.env before real tutors submit W-9 forms."
    )

_fernets = [Fernet(k.encode() if isinstance(k, str) else k) for k in _raw_keys]
_tin_cipher = MultiFernet(_fernets)


def encrypt_tin(tin_digits: str) -> str:
    return _tin_cipher.encrypt(tin_digits.encode()).decode()


def decrypt_tin(token: str) -> str:
    """Decrypt a TIN token, falling back to legacy base64. Returns "" if undecodable (never raises)."""
    if not token:
        return ""
    try:
        return _tin_cipher.decrypt(token.encode()).decode()
    except InvalidToken:
        try:
            return base64.b64decode(token.encode()).decode()
        except (binascii.Error, UnicodeDecodeError, ValueError):
            return ""


def is_legacy_tin_token(token: str) -> bool:
    if not token:
        return False
    try:
        _tin_cipher.decrypt(token.encode())
        return False
    except InvalidToken:
        return True


# ---- Auth helpers ----
SUSPENDED_MSG = "Your account is paused while the Babybabel team reviews it. Please contact support."


def hash_password(p: str) -> str:
    return bcrypt.hashpw(p.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(p: str, h: str) -> bool:
    try:
        return bcrypt.checkpw(p.encode(), h.encode())
    except Exception:
        return False


def session_minutes(user: dict) -> int:
    return ADMIN_SESSION_MINUTES if user.get("is_admin") else ACCESS_TOKEN_MINUTES


def make_token(user_id: str, role: str, token_version: int = 0, minutes: Optional[int] = None, admin: bool = False) -> str:
    now = now_utc()
    payload = {"sub": user_id, "role": role, "tv": token_version, "iat": now,
               "exp": now + timedelta(minutes=minutes or ACCESS_TOKEN_MINUTES)}
    if admin:
        payload["adm"] = True  # only set by the admin sign-in that checked the emailed code
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_code() -> str:
    """6-digit one-time code for email verification / password reset."""
    return f"{secrets.randbelow(1_000_000):06d}"


def email_fingerprint(email: str) -> str:
    """Stable, non-reversible id for an email (lower-cased, +tag stripped) — survives account deletion."""
    local, _, domain = email.lower().strip().partition("@")
    local = local.split("+", 1)[0]
    if domain in ("gmail.com", "googlemail.com"):  # Gmail ignores dots
        local, domain = local.replace(".", ""), "gmail.com"
    return hashlib.sha256(f"{local}@{domain}".encode()).hexdigest()


def _token_valid_for(user: dict, payload: dict) -> bool:
    """Changing the password bumps token_version, which voids every token issued before.
    An admin account only accepts tokens from the admin sign-in (password + emailed code), and
    only for ADMIN_SESSION_MINUTES, so a token from signup, a password reset or an old session
    never opens the admin tools."""
    if int(payload.get("tv", 0)) != int(user.get("token_version", 0)):
        return False
    if user.get("is_admin"):
        if not payload.get("adm"):
            return False
        issued = payload.get("iat")
        if not isinstance(issued, (int, float)) or time.time() - issued > ADMIN_SESSION_MINUTES * 60:
            return False
    return True


async def _user_from_token(token: Optional[str]) -> Optional[dict]:
    if not token:
        return None
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except Exception:
        return None
    user = await db.users.find_one({"id": payload.get("sub")}, {"_id": 0})
    if not user or not _token_valid_for(user, payload):
        return None
    return user


# ---- Sessions: bearer token (phone apps) or HttpOnly cookie (website) ----
# The website keeps its sign-in in a cookie page scripts can't read, so an injected script
# can't steal it. Cookie requests that change anything must also send X-Babybabel-CSRF: 1 —
# a custom header other websites can't add — which, with SameSite=Strict, stops cross-site forgery.
SESSION_COOKIE = "bb_session"
CSRF_HEADER = "x-babybabel-csrf"
COOKIE_SECURE = not PUBLIC_WEB_URL.startswith("http://")  # http only for local development
_SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


async def request_token(request: Request, bearer: Optional[str] = Depends(oauth2_scheme)) -> Optional[str]:
    if bearer:
        return bearer
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    if request.method not in _SAFE_METHODS and request.headers.get(CSRF_HEADER) != "1":
        raise HTTPException(403, "Missing security header")
    return token


def wants_cookie_session(request: Request) -> bool:
    return request.headers.get("x-session-mode", "").lower() == "cookie"


def set_session_cookie(response, token: str, minutes: Optional[int] = None) -> None:
    response.set_cookie(
        SESSION_COOKIE, token, max_age=(minutes or ACCESS_TOKEN_MINUTES) * 60, httponly=True,
        secure=COOKIE_SECURE, samesite="strict", path="/api",
    )


def clear_session_cookie(response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/api", secure=COOKIE_SECURE, httponly=True, samesite="strict")


async def _token_user(token: Optional[str]) -> dict:
    if not token:
        raise HTTPException(401, "Not authenticated")
    user = await _user_from_token(token)
    if not user:
        raise HTTPException(401, "Invalid token")
    return user


async def current_user(token: Optional[str] = Depends(request_token)) -> dict:
    user = await _token_user(token)
    if user.get("suspended") and not user.get("is_admin"):
        raise HTTPException(423, SUSPENDED_MSG)
    return user


async def current_user_even_if_paused(token: Optional[str] = Depends(request_token)) -> dict:
    """Used only for account deletion — a paused user may still delete their data."""
    return await _token_user(token)


async def optional_user(token: Optional[str] = Depends(request_token)) -> Optional[dict]:
    """Same as current_user but returns None (not 401) when no valid token."""
    user = await _user_from_token(token)
    return None if (user and user.get("suspended") and not user.get("is_admin")) else user


async def require_admin(u: dict = Depends(current_user)) -> dict:
    if not u.get("is_admin"):
        raise HTTPException(403, "Admin only")
    return u


def email_is_verified(u: dict) -> bool:
    # Accounts created before verification existed have no flag and count as verified.
    return u.get("email_verified", True) is not False


def require_verified_email(u: dict) -> None:
    if REQUIRE_EMAIL_VERIFICATION and not email_is_verified(u) and not u.get("is_admin"):
        raise HTTPException(403, "Please verify your email address first (Profile → Verify email).")


# ---- Blocks ----
BLOCKED_MSG = "You can no longer contact this person."


async def blocked_between(a: str, b: str) -> bool:
    return bool(await db.blocks.find_one({"$or": [
        {"blocker_id": a, "blocked_id": b}, {"blocker_id": b, "blocked_id": a},
    ]}, {"_id": 1}))


async def blocked_user_ids(uid: str) -> set:
    """Everyone this user blocked or was blocked by."""
    docs = await db.blocks.find({"$or": [{"blocker_id": uid}, {"blocked_id": uid}]}, {"_id": 0, "blocker_id": 1, "blocked_id": 1}).to_list(5000)
    return {d["blocked_id"] if d["blocker_id"] == uid else d["blocker_id"] for d in docs}


# ---- Tutor id helpers ----
# NOTE: booking["tutor_id"] is the tutor PROFILE id (db.tutors.id), not the tutor's user id.
async def tutor_profile_id(user_id: str) -> Optional[str]:
    t = await db.tutors.find_one({"user_id": user_id}, {"_id": 0, "id": 1})
    return t["id"] if t else None


async def tutor_user_id(profile_id: str) -> Optional[str]:
    t = await db.tutors.find_one({"id": profile_id}, {"_id": 0, "user_id": 1})
    return t["user_id"] if t else None


async def tutor_has_completed_session(user_id: str) -> Optional[dict]:
    """Return the earliest completed paid booking for this tutor (or None)."""
    pid = await tutor_profile_id(user_id)
    if not pid:
        return None
    now = now_utc()
    docs = await db.bookings.find({"tutor_id": pid, "payment_status": "paid"}, {"_id": 0}).sort("date", 1).to_list(200)
    for b in docs:
        end = booking_end_utc(b)
        if end and end < now:
            return b
    return None


# ---- Notifications (in-app records + Expo push) ----
EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
PUSH_ENABLED = os.environ.get("PUSH_ENABLED", "true").lower() == "true"
_background_tasks: set = set()


def run_in_background(coro) -> None:
    """Fire-and-forget a coroutine, keeping a reference so it isn't garbage-collected mid-flight."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def send_push(user_id: str, title: str, body: str, data: Optional[dict] = None) -> None:
    """Deliver to every Expo push token the user registered. Never raises."""
    if not PUSH_ENABLED:
        return
    try:
        tokens = [t["token"] for t in await db.push_tokens.find({"user_id": user_id}, {"_id": 0, "token": 1}).to_list(20)]
        if not tokens:
            return
        messages = [{"to": t, "title": title, "body": body[:180], "sound": "default", "data": data or {}} for t in tokens]
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if os.environ.get("EXPO_ACCESS_TOKEN"):
            headers["Authorization"] = f"Bearer {os.environ['EXPO_ACCESS_TOKEN']}"
        async with httpx.AsyncClient(timeout=15) as c:
            resp = await c.post(EXPO_PUSH_URL, json=messages, headers=headers)
        tickets = (resp.json() or {}).get("data") or []
        for tok, ticket in zip(tokens, tickets):
            if ticket.get("status") == "error" and (ticket.get("details") or {}).get("error") == "DeviceNotRegistered":
                await db.push_tokens.delete_one({"token": tok})
    except Exception as e:
        logger.warning(f"push to {user_id} failed: {e}")


async def push_notification(user_id: str, kind: str, title: str, body: str, data: Optional[dict] = None) -> None:
    await db.notifications.insert_one({
        "id": str(uuid.uuid4()), "user_id": user_id, "kind": kind,
        "title": title, "body": body, "read": False, "at": now_iso(),
    })
    run_in_background(send_push(user_id, title, push_text(kind, body), {"kind": kind, **(data or {})}))


async def notify_once(user_id: str, kind: str, title: str, body: str, data: Optional[dict] = None) -> bool:
    """Create a notification unless one with this exact kind already exists for the user."""
    if await db.notifications.find_one({"user_id": user_id, "kind": kind}, {"_id": 1}):
        return False
    await push_notification(user_id, kind, title, body, data)
    return True


async def notify_admins(kind: str, title: str, body: str) -> None:
    for a in await db.users.find({"is_admin": True}, {"_id": 0, "id": 1}).to_list(20):
        await push_notification(a["id"], kind, title, body)


def today_in(tz_name: Optional[str]) -> date_cls:
    return now_utc().astimezone(zone(tz_name)).date()


# ---- Tutor verification (required before anyone can book a tutor) ----
NOT_VERIFIED_MSG = "This tutor hasn't finished identity and background verification yet, so they can't take bookings."
TUTOR_NOT_VERIFIED_MSG = ("Finish identity and background verification before offering lessons "
                          "(Profile → Identity & background check). Our team reviews it within 1–2 working days.")


def is_tutor_verified(t: Optional[dict]) -> bool:
    return bool(t) and t.get("verification_status") == "verified"


# ---- Signed, short-lived links to private files ----
# Images and documents can't send the sign-in header, so after checking access the API hands
# out a link that works for one file for a few minutes (like an S3 pre-signed URL).
_FILE_URL_KEY = hashlib.sha256(b"babybabel-file-url:" + JWT_SECRET.encode()).digest()
FILE_URL_MINUTES = 15


def _file_sig(path: str, exp: int) -> str:
    import hmac
    return hmac.new(_FILE_URL_KEY, f"{path}|{exp}".encode(), hashlib.sha256).hexdigest()[:40]


def signed_file_url(path: str, minutes: int = FILE_URL_MINUTES) -> str:
    exp = int(time.time()) + minutes * 60
    return f"/api/files/{path}?exp={exp}&sig={_file_sig(path, exp)}"


def file_signature_ok(path: str, exp: Optional[str], sig: Optional[str]) -> bool:
    import hmac
    try:
        exp_i = int(exp or "0")
    except ValueError:
        return False
    if not sig or exp_i < time.time() or exp_i > time.time() + 24 * 3600:
        return False
    return hmac.compare_digest(sig, _file_sig(path, exp_i))


async def check_own_files(user_id: str, new_values: list, current_values: list) -> None:
    """A profile may only point at files its owner uploaded (or keep what it already has).
    Stops someone saving another family's private photo path into their own profile."""
    allowed = {v for v in current_values if v}
    for v in new_values:
        if not v or v in allowed:
            continue
        path = str(v).split("/api/files/", 1)[-1].split("?", 1)[0]
        if not await db.uploads.find_one({"path": path, "owner_id": user_id}, {"_id": 1}):
            raise HTTPException(422, "Photos and documents must be uploaded from your own device.")


def push_text(kind: str, body: str) -> str:
    """What a push notification shows on a lock screen. Message text stays inside the app."""
    return "Open Babybabel to read it." if kind in ("chat", "invitation") else body
