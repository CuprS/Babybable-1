import os
import uuid
import logging
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Literal

import bcrypt
import jwt
import stripe
from dotenv import load_dotenv
from fastapi import FastAPI, APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Request, Header
from fastapi.responses import Response, StreamingResponse
from fastapi.security import OAuth2PasswordBearer
from starlette.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, EmailStr, Field
import io
import math
import re
import time
import threading
import base64
import binascii
from cryptography.fernet import Fernet, MultiFernet, InvalidToken
from collections import defaultdict, deque

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
APP_NAME = os.environ.get("APP_NAME", "babybabel")

STORAGE_BASE = (os.environ.get("INTEGRATION_PROXY_URL") or "").strip() or "https://integrations.emergentagent.com"
STORAGE_URL = STORAGE_BASE.rstrip("/") + "/objstore/api/v1/storage"
EMERGENT_KEY = os.environ.get("EMERGENT_LLM_KEY")

stripe.api_key = os.environ.get("STRIPE_API_KEY", "")

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]

logger = logging.getLogger("babybabel")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ---- App ----
app = FastAPI(title="Babybabel API")
api = APIRouter(prefix="/api")

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

# ---- Storage (Emergent Managed Object Storage) ----
_storage_key: Optional[str] = None


def _init_storage_sync() -> str:
    global _storage_key
    if _storage_key:
        return _storage_key
    resp = requests.post(f"{STORAGE_URL}/init", json={"emergent_key": EMERGENT_KEY}, timeout=30)
    resp.raise_for_status()
    _storage_key = resp.json()["storage_key"]
    return _storage_key


def _put_object_sync(path: str, data: bytes, content_type: str) -> dict:
    key = _init_storage_sync()
    resp = requests.put(
        f"{STORAGE_URL}/objects/{path}",
        headers={"X-Storage-Key": key, "Content-Type": content_type},
        data=data,
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()


def _get_object_sync(path: str):
    global _storage_key
    key = _init_storage_sync()
    resp = requests.get(f"{STORAGE_URL}/objects/{path}", headers={"X-Storage-Key": key}, timeout=60)
    if resp.status_code == 503:
        _storage_key = None
        key = _init_storage_sync()
        resp = requests.get(f"{STORAGE_URL}/objects/{path}", headers={"X-Storage-Key": key}, timeout=60)
    resp.raise_for_status()
    return resp.content, resp.headers.get("Content-Type", "application/octet-stream")


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
                headers={"User-Agent": f"{APP_NAME}/1.0 (contact: help@babybabel.co)"},
                timeout=8,
            )
            _last_geocode_at = time.time()
        resp.raise_for_status()
        arr = resp.json()
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


# ---- Rate limiter (in-memory, per-IP) ----
_rate_lock = threading.Lock()
_rate_buckets: dict = defaultdict(deque)


def _client_ip(request: Request) -> str:
    """Return the caller's IP.
    We're behind Kubernetes ingress which APPENDS the real client IP as the
    right-most value in X-Forwarded-For (any left-side values are attacker-controlled).
    Fall back to X-Real-IP, then the direct client host."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            return parts[-1]
    real = request.headers.get("x-real-ip")
    if real:
        return real.strip()
    return request.client.host if request.client else "unknown"


def rate_limit(bucket: str, max_hits: int, per_seconds: int, request: Request) -> None:
    """Simple sliding-window rate limit keyed by bucket + IP."""
    key = f"{bucket}:{_client_ip(request)}"
    now = time.time()
    with _rate_lock:
        dq = _rate_buckets[key]
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


# ---- Slot / weekday helpers ----
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def weekday_key(date_str: str) -> Optional[str]:
    try:
        y, m, d = date_str.split("-")
        # Python: Monday = 0
        idx = datetime(int(y), int(m), int(d)).weekday()
        return WEEKDAYS[idx]
    except Exception:
        return None


def _normalize_slot(t: str) -> str:
    """'9:00' -> '09:00'. Returns '' on garbage input."""
    try:
        h, mm = t.split(":")
        return f"{int(h):02d}:{int(mm):02d}"
    except Exception:
        return ""


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


async def is_slot_booked(tutor_id: str, date: str, time_str: str, exclude_booking_id: Optional[str] = None) -> bool:
    q: dict = {
        "tutor_id": tutor_id,
        "date": date,
        "time": _normalize_slot(time_str),
        "payment_status": {"$ne": "canceled"},
    }
    if exclude_booking_id:
        q["id"] = {"$ne": exclude_booking_id}
    return bool(await db.bookings.find_one(q, {"_id": 0, "id": 1}))


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
    if await db.platform_earnings.find_one({"booking_id": booking["id"]}, {"_id": 0, "id": 1}):
        return  # already credited
    admin = await db.users.find_one({"is_admin": True}, {"_id": 0, "id": 1})
    await db.platform_earnings.insert_one({
        "id": str(uuid.uuid4()),
        "booking_id": booking["id"],
        "admin_user_id": (admin or {}).get("id"),
        "parent_id": booking.get("parent_id"),
        "tutor_id": booking.get("tutor_id"),
        "amount_cents": fee,
        "currency": booking.get("currency", "usd"),
        "at": datetime.now(timezone.utc).isoformat(),
    })


# ---- TIN encryption (Fernet + MultiFernet key rotation) ----
# Reads a comma-separated list of Fernet keys from env W9_ENCRYPTION_KEYS.
# First key is used to encrypt new TINs; all keys are tried for decryption,
# enabling zero-downtime rotation: add a new key at the front, keep the old
# one at the back until every W-9 has been re-saved by its tutor.
_W9_KEYS_ENV = os.getenv("W9_ENCRYPTION_KEYS", "").strip()
if _W9_KEYS_ENV:
    _raw_keys = [k.strip() for k in _W9_KEYS_ENV.split(",") if k.strip()]
    _EPHEMERAL_W9_KEY = False
else:
    _generated = Fernet.generate_key().decode()
    _raw_keys = [_generated]
    _EPHEMERAL_W9_KEY = True
    logger.warning(
        "W9_ENCRYPTION_KEYS is not set — generated a one-off in-memory key. "
        "Set W9_ENCRYPTION_KEYS in backend/.env before real tutors submit W-9 forms."
    )

_fernets = [Fernet(k.encode() if isinstance(k, str) else k) for k in _raw_keys]
_tin_cipher = MultiFernet(_fernets)


def encrypt_tin(tin_digits: str) -> str:
    """Encrypt a TIN using the primary key."""
    return _tin_cipher.encrypt(tin_digits.encode()).decode()


def decrypt_tin(token: str) -> str:
    """Decrypt a TIN token. Falls back to legacy base64 for one-time migration.

    Returns "" if the token cannot be decoded (never raises)."""
    if not token:
        return ""
    try:
        return _tin_cipher.decrypt(token.encode()).decode()
    except InvalidToken:
        # Legacy: raw base64(tin) from the pre-Fernet scheme. Migrate on next write.
        try:
            return base64.b64decode(token.encode()).decode()
        except (binascii.Error, UnicodeDecodeError, ValueError):
            return ""


def is_legacy_tin_token(token: str) -> bool:
    """A modern Fernet token can be decrypted by the current cipher; anything else is legacy."""
    if not token:
        return False
    try:
        _tin_cipher.decrypt(token.encode())
        return False
    except InvalidToken:
        return True
# ---- End TIN encryption ----


# ---- Models ----

Role = Literal["parent", "tutor", "admin"]


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    name: str = Field(min_length=1, max_length=80)
    role: Role


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserPublic(BaseModel):
    id: str
    email: EmailStr
    name: str
    role: Role
    avatar_url: Optional[str] = None
    is_admin: bool = False


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserPublic


class TutorLocation(BaseModel):
    name: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class TutorProfile(BaseModel):
    id: str
    user_id: str
    name: str
    avatar_url: Optional[str] = None
    bio: str = ""
    languages: List[str] = []
    hourly_rate_cents: int = 3000
    currency: str = "usd"
    location: str = ""  # legacy — primary location name
    latitude: Optional[float] = None  # legacy — primary lat
    longitude: Optional[float] = None  # legacy — primary lng
    locations: List[TutorLocation] = []
    allows_remote: bool = False
    experience_years: int = 0
    rating: float = 0.0
    reviews_count: int = 0
    accreditation_urls: List[str] = []  # legacy
    accreditation_photo_url: Optional[str] = None
    accreditation_document_url: Optional[str] = None
    hero_image_url: Optional[str] = None
    is_new: bool = False
    # Weekly recurring availability. Keys: mon/tue/wed/thu/fri/sat/sun.
    # Values: sorted list of "HH:MM" slot starts the tutor is available.
    # Empty dict or empty list = "no restrictions set" (all slots open for backward compat).
    weekly_availability: dict = Field(default_factory=dict)
    # Populated only by list_tutors when the caller is a parent with saved coordinates.
    distance_miles: Optional[float] = None


class TutorProfileUpdate(BaseModel):
    bio: Optional[str] = None
    languages: Optional[List[str]] = None
    hourly_rate_cents: Optional[int] = None
    locations: Optional[List[str]] = None  # accept plain names, we geocode
    experience_years: Optional[int] = None
    avatar_url: Optional[str] = None
    hero_image_url: Optional[str] = None
    accreditation_photo_url: Optional[str] = None
    accreditation_document_url: Optional[str] = None
    allows_remote: Optional[bool] = None
    weekly_availability: Optional[dict] = None


class BookingCreate(BaseModel):
    tutor_id: str
    date: str
    time: str
    duration_minutes: int = Field(gt=0, le=480)
    language: str
    notes: Optional[str] = ""
    is_au_pair: bool = False
    lessons_count: int = Field(default=1, ge=1, le=200)
    housing_offered: Optional[str] = Field(default="", max_length=800)


class Booking(BaseModel):
    id: str
    parent_id: str
    parent_name: str
    tutor_id: str
    tutor_name: str
    date: str
    time: str
    duration_minutes: int
    language: str
    amount_cents: int
    platform_fee_cents: int = 0
    currency: str
    payment_status: str
    stripe_payment_intent_id: Optional[str] = None
    client_secret: Optional[str] = None
    notes: Optional[str] = ""
    is_au_pair: bool = False
    lessons_count: int = 1
    distance_miles: Optional[float] = None
    remote: bool = False
    housing_offered: Optional[str] = ""
    created_at: str


class MessageCreate(BaseModel):
    to_user_id: str
    text: str


class Invitation(BaseModel):
    price_cents: int = Field(ge=100)
    date: str
    time: str
    duration_minutes: int = Field(gt=0, le=480)
    language: str
    note: Optional[str] = ""
    status: str = "pending"  # pending | accepted | declined
    booking_id: Optional[str] = None


class InvitationCreate(BaseModel):
    to_user_id: str
    price_cents: int = Field(ge=100)
    date: str
    time: str
    duration_minutes: int = Field(gt=0, le=480)
    language: str
    note: Optional[str] = ""


class Message(BaseModel):
    id: str
    from_user_id: str
    to_user_id: str
    text: str
    kind: str = "text"
    invitation: Optional[Invitation] = None
    created_at: str


class Child(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    age: int = Field(ge=0, le=18)
    avatar_url: Optional[str] = None


class ParentProfile(BaseModel):
    user_id: str
    name: str
    avatar_url: Optional[str] = None
    city: str = ""
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    languages_desired: List[str] = []
    hours_per_week: int = 5
    learning_materials: str = ""
    children: List[Child] = []


class ParentProfileUpdate(BaseModel):
    name: Optional[str] = None
    avatar_url: Optional[str] = None
    city: Optional[str] = None
    languages_desired: Optional[List[str]] = None
    hours_per_week: Optional[int] = None
    learning_materials: Optional[str] = None
    children: Optional[List[Child]] = None


class ReviewCreate(BaseModel):
    tutor_id: str
    booking_id: Optional[str] = None
    rating: int = Field(ge=1, le=5)
    comment: str = ""


class Review(BaseModel):
    id: str
    tutor_id: str
    booking_id: Optional[str] = None
    parent_id: str
    parent_name: str
    rating: int
    comment: str
    created_at: str


# ---- W-9 Tax form ----
class W9FormIn(BaseModel):
    # Line 1
    legal_name: str = Field(min_length=1, max_length=140)
    # Line 2 (DBA / business name)
    business_name: Optional[str] = Field(default="", max_length=140)
    # Line 3 — federal tax classification
    tax_classification: str  # one of: individual, sole_proprietor, c_corp, s_corp, partnership, trust_estate, llc, other
    llc_tax_class: Optional[str] = Field(default="", max_length=1)  # C, S, or P (only if llc)
    other_classification: Optional[str] = Field(default="", max_length=80)
    # Line 5 & 6 — address
    address: str = Field(min_length=1, max_length=200)
    city: str = Field(min_length=1, max_length=80)
    state: str = Field(min_length=1, max_length=40)
    zip_code: str = Field(min_length=1, max_length=20)
    country: Optional[str] = Field(default="US", max_length=40)
    # Part I — Taxpayer ID
    tin_type: str  # "ssn" or "ein"
    tin: str = Field(min_length=5, max_length=20)
    # Part II — signature (typed)
    signature_name: str = Field(min_length=1, max_length=140)
    is_us_person: bool = True
    exempt_from_backup: bool = False


class W9Form(BaseModel):
    id: str
    tutor_user_id: str
    tutor_name: str
    tutor_email: str
    legal_name: str
    business_name: str = ""
    tax_classification: str
    llc_tax_class: str = ""
    other_classification: str = ""
    address: str
    city: str
    state: str
    zip_code: str
    country: str = "US"
    tin_type: str
    tin_masked: str  # last-4 only for admin list view
    signature_name: str
    is_us_person: bool
    exempt_from_backup: bool
    signed_at: str
    updated_at: str


# ---- Auth helpers ----
def hash_password(p: str) -> str:
    return bcrypt.hashpw(p.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(p: str, h: str) -> bool:
    try:
        return bcrypt.checkpw(p.encode(), h.encode())
    except Exception:
        return False


def make_token(user_id: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": user_id, "role": role, "iat": now, "exp": now + timedelta(minutes=ACCESS_TOKEN_MINUTES)}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


async def current_user(token: Optional[str] = Depends(oauth2_scheme)) -> dict:
    if not token:
        raise HTTPException(401, "Not authenticated")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload["sub"]
    except Exception:
        raise HTTPException(401, "Invalid token")
    user = await db.users.find_one({"id": user_id}, {"_id": 0})
    if not user:
        raise HTTPException(401, "User not found")
    return user


async def optional_user(token: Optional[str] = Depends(oauth2_scheme)) -> Optional[dict]:
    """Same as current_user but returns None (not 401) when no valid token."""
    if not token:
        return None
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return await db.users.find_one({"id": payload["sub"]}, {"_id": 0})
    except Exception:
        return None


def user_to_public(u: dict) -> UserPublic:
    return UserPublic(id=u["id"], email=u["email"], name=u["name"], role=u["role"], avatar_url=u.get("avatar_url"), is_admin=bool(u.get("is_admin")))


async def require_admin(u: dict = Depends(current_user)) -> dict:
    if not u.get("is_admin"):
        raise HTTPException(403, "Admin only")
    return u


# ---- Auth routes ----
@api.post("/auth/signup", response_model=AuthResponse, status_code=201)
async def signup(body: SignupRequest, request: Request):
    rate_limit("signup", max_hits=5, per_seconds=600, request=request)
    email = body.email.lower().strip()
    if body.role not in ("parent", "tutor"):
        # Admin roles are provisioned server-side only; never accept via signup.
        raise HTTPException(400, "Invalid role")
    existing = await db.users.find_one({"email": email})
    if existing:
        # Generic error prevents easy email enumeration via signup.
        raise HTTPException(400, "We couldn't create that account. Try logging in or use a different email.")
    uid = str(uuid.uuid4())
    doc = {
        "id": uid,
        "email": email,
        "password_hash": hash_password(body.password),
        "name": body.name,
        "role": body.role,
        "avatar_url": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.users.insert_one(doc)
    # If tutor, create an empty tutor profile
    if body.role == "tutor":
        tid = str(uuid.uuid4())
        await db.tutors.insert_one({
            "id": tid, "user_id": uid, "name": body.name, "avatar_url": None,
            "bio": "", "languages": [], "hourly_rate_cents": 3000, "currency": "usd",
            "location": "", "experience_years": 0, "rating": 0.0, "reviews_count": 0,
            "accreditation_urls": [], "hero_image_url": None,
            "weekly_availability": {},
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    return AuthResponse(access_token=make_token(uid, body.role), user=user_to_public(doc))


@api.post("/auth/login", response_model=AuthResponse)
async def login(body: LoginRequest, request: Request):
    rate_limit("login", max_hits=8, per_seconds=300, request=request)
    email = body.email.lower().strip()
    u = await db.users.find_one({"email": email})
    if not u or not verify_password(body.password, u["password_hash"]):
        raise HTTPException(401, "Invalid email or password")
    return AuthResponse(access_token=make_token(u["id"], u["role"]), user=user_to_public(u))


@api.get("/auth/me", response_model=UserPublic)
async def me(u: dict = Depends(current_user)):
    return user_to_public(u)


class UserUpdate(BaseModel):
    name: Optional[str] = None
    avatar_url: Optional[str] = None


@api.patch("/auth/me", response_model=UserPublic)
async def update_me(patch: UserUpdate, u: dict = Depends(current_user)):
    update = patch.model_dump(exclude_none=True)
    if update:
        await db.users.update_one({"id": u["id"]}, {"$set": update})
        # sync to role profile
        if u["role"] == "tutor":
            await db.tutors.update_one({"user_id": u["id"]}, {"$set": update})
        else:
            await db.parents.update_one({"user_id": u["id"]}, {"$set": update}, upsert=True)
    fresh = await db.users.find_one({"id": u["id"]}, {"_id": 0})
    return user_to_public(fresh)


# ---- Uploads ----
@api.post("/uploads")
async def upload(file: UploadFile = File(...), u: dict = Depends(current_user)):
    ext = (file.filename or "file").split(".")[-1].lower()
    IMAGE_EXTS = ("jpg", "jpeg", "png", "webp", "heic", "heif")
    DOC_EXTS = ("pdf", "doc", "docx", "rtf", "txt")
    if ext not in IMAGE_EXTS and ext not in DOC_EXTS:
        ext = "jpg"
    path = f"{APP_NAME}/uploads/{u['id']}/{uuid.uuid4()}.{ext}"
    data = await file.read()
    ctype = file.content_type or ("application/pdf" if ext == "pdf" else "image/jpeg")
    try:
        await run_in_threadpool(_put_object_sync, path, data, ctype)
    except Exception as e:
        logger.exception("upload failed")
        raise HTTPException(502, f"Upload failed: {e}")
    await db.uploads.insert_one({
        "path": path, "owner_id": u["id"], "content_type": ctype,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return {"path": path, "url": f"/api/files/{path}", "content_type": ctype}


@api.get("/files/{path:path}")
async def get_file(path: str, token: Optional[str] = None, u_maybe: Optional[str] = Depends(oauth2_scheme)):
    rec = await db.uploads.find_one({"path": path}, {"_id": 0})
    if not rec:
        raise HTTPException(404, "File not found")

    # Classify the file's sensitivity by looking up who references it.
    # - private: children photos (owner-only)
    # - restricted: tutor accreditation docs/photos, W-9 references (any logged-in user)
    # - public: everything else (avatars, hero images)
    child_ref = await db.parents.find_one({"children.avatar_url": path}, {"_id": 0, "user_id": 1})
    accreditation_ref = None
    if not child_ref:
        accreditation_ref = await db.tutors.find_one(
            {"$or": [
                {"accreditation_photo_url": path},
                {"accreditation_document_url": path},
                {"accreditation_urls": path},
            ]},
            {"_id": 0, "user_id": 1},
        )

    tok = u_maybe or token
    caller: Optional[dict] = None
    if tok:
        try:
            payload = jwt.decode(tok, JWT_SECRET, algorithms=[JWT_ALGORITHM])
            caller = await db.users.find_one({"id": payload.get("sub")}, {"_id": 0})
        except Exception:
            caller = None

    is_private = bool(child_ref)
    is_restricted = bool(accreditation_ref)

    if is_private:
        if not caller:
            raise HTTPException(401, "Auth required for private file")
        if caller["id"] != child_ref["user_id"] and not caller.get("is_admin"):
            raise HTTPException(403, "Not your file")
    elif is_restricted:
        # Any authenticated user (parent/tutor/admin) can view accreditation documents.
        if not caller:
            raise HTTPException(401, "Auth required to view accreditation documents")

    try:
        content, ctype = await run_in_threadpool(_get_object_sync, path)
    except Exception as e:
        logger.exception("download failed")
        raise HTTPException(502, f"Download failed: {e}")

    # SEC-003 remediation: never let a shared cache/CDN store gated files.
    cache_header = "public, max-age=86400" if (not is_private and not is_restricted) else "private, no-store"
    return Response(content=content, media_type=ctype, headers={"Cache-Control": cache_header})


# ---- Tutors ----
def tutor_doc_to_model(t: dict) -> TutorProfile:
    is_new = not (t.get("bio") and t.get("languages") and t.get("avatar_url"))
    # Backfill locations from legacy 'location'
    locs = t.get("locations")
    if not locs and t.get("location"):
        locs = [{"name": t["location"], "latitude": t.get("latitude"), "longitude": t.get("longitude")}]
    locs = locs or []
    primary = locs[0] if locs else {}
    data = {k: t.get(k) for k in TutorProfile.model_fields.keys() if k not in ("is_new", "locations", "location", "latitude", "longitude")}
    # Defensive: coerce None -> defaults for fields that don't allow None
    if data.get("allows_remote") is None:
        data["allows_remote"] = False
    if data.get("weekly_availability") is None:
        data["weekly_availability"] = {}
    for k in ("bio", "currency"):
        if data.get(k) is None:
            data[k] = "" if k != "currency" else "usd"
    for k in ("languages", "accreditation_urls"):
        if data.get(k) is None:
            data[k] = []
    for k in ("hourly_rate_cents", "experience_years", "reviews_count"):
        if data.get(k) is None:
            data[k] = 0
    if data.get("rating") is None:
        data["rating"] = 0.0
    return TutorProfile(
        **data,
        is_new=is_new,
        locations=[TutorLocation(**l) for l in locs],
        location=primary.get("name", "") or t.get("location", ""),
        latitude=primary.get("latitude") if primary else t.get("latitude"),
        longitude=primary.get("longitude") if primary else t.get("longitude"),
    )



async def maybe_geocode_and_persist(collection, filter_q: dict, location_str: str, previous: Optional[dict]):
    """Geocode a location string if it changed vs the previous doc."""
    if not location_str:
        return
    prev_loc = (previous or {}).get("location") or (previous or {}).get("city") or ""
    if prev_loc.strip().lower() == location_str.strip().lower() and (previous or {}).get("latitude") is not None:
        return
    coords = await run_in_threadpool(geocode, location_str)
    if coords:
        await collection.update_one(filter_q, {"$set": coords})



@api.get("/tutors", response_model=List[TutorProfile])
async def list_tutors(
    q: Optional[str] = None,
    language: Optional[str] = None,
    min_rate: Optional[int] = None,
    max_rate: Optional[int] = None,
    max_miles: Optional[float] = None,
    include_remote: bool = True,
    u: Optional[dict] = Depends(optional_user),
):
    query: dict = {}
    if language:
        query["languages"] = {"$regex": f"^{language}$", "$options": "i"}
    if min_rate is not None:
        query.setdefault("hourly_rate_cents", {})["$gte"] = min_rate
    if max_rate is not None:
        query.setdefault("hourly_rate_cents", {})["$lte"] = max_rate
    if q:
        # Escape user input so a crafted regex can't pin DB CPU (ReDoS) or match unexpected fields.
        needle = re.escape(q.strip())[:80]
        query["$or"] = [
            {"name": {"$regex": needle, "$options": "i"}},
            {"bio": {"$regex": needle, "$options": "i"}},
            {"location": {"$regex": needle, "$options": "i"}},
            {"languages": {"$regex": needle, "$options": "i"}},
        ]
    docs = await db.tutors.find(query, {"_id": 0}).to_list(200)

    # Distance filter — only when the caller is a parent with saved coordinates.
    parent_coords = None
    if u and u.get("role") == "parent":
        p = await db.parents.find_one({"user_id": u["id"]}, {"_id": 0, "latitude": 1, "longitude": 1})
        if p and p.get("latitude") is not None and p.get("longitude") is not None:
            parent_coords = (p["latitude"], p["longitude"])

    def closest_distance(doc: dict) -> Optional[float]:
        if not parent_coords:
            return None
        best: Optional[float] = None
        for loc in (doc.get("locations") or []):
            if loc.get("latitude") is None:
                continue
            d = haversine_miles(parent_coords[0], parent_coords[1], loc["latitude"], loc["longitude"])
            if best is None or d < best:
                best = d
        if best is None and doc.get("latitude") is not None:
            best = haversine_miles(parent_coords[0], parent_coords[1], doc["latitude"], doc["longitude"])
        return round(best, 1) if best is not None else None

    out: List[TutorProfile] = []
    for d in docs:
        model = tutor_doc_to_model(d)
        model.distance_miles = closest_distance(d)
        if max_miles is not None and parent_coords is not None:
            # Include remote-friendly tutors if the toggle is on.
            if model.distance_miles is None:
                if not (include_remote and model.allows_remote):
                    continue
            elif model.distance_miles > max_miles:
                if not (include_remote and model.allows_remote):
                    continue
        out.append(model)

    # Sort nearest-first when we have coords, else preserve DB order.
    if parent_coords is not None:
        out.sort(key=lambda t: (t.distance_miles is None, t.distance_miles or 0))
    return out


@api.get("/tutors/map")
async def tutors_map():
    docs = await db.tutors.find(
        {},
        {"_id": 0, "id": 1, "name": 1, "avatar_url": 1, "latitude": 1, "longitude": 1, "location": 1, "locations": 1, "hourly_rate_cents": 1, "allows_remote": 1},
    ).to_list(200)
    out = []
    for d in docs:
        locs = d.get("locations") or ([{"name": d.get("location"), "latitude": d.get("latitude"), "longitude": d.get("longitude")}] if d.get("latitude") is not None else [])
        for l in locs:
            if l.get("latitude") is None or l.get("longitude") is None:
                continue
            out.append({
                "id": d["id"], "name": d["name"], "avatar_url": d.get("avatar_url"),
                "latitude": l["latitude"], "longitude": l["longitude"],
                "location": l.get("name"),
                "hourly_rate_cents": d.get("hourly_rate_cents"),
                "allows_remote": d.get("allows_remote", False),
            })
    return out


@api.get("/tutors/{tutor_id}", response_model=TutorProfile)
async def get_tutor(tutor_id: str):
    d = await db.tutors.find_one({"id": tutor_id}, {"_id": 0})
    if not d:
        raise HTTPException(404, "Tutor not found")
    return tutor_doc_to_model(d)


@api.get("/tutors/me/profile", response_model=TutorProfile)
async def get_my_tutor_profile(u: dict = Depends(current_user)):
    if u["role"] != "tutor":
        raise HTTPException(403, "Only tutors")
    d = await db.tutors.find_one({"user_id": u["id"]}, {"_id": 0})
    if not d:
        raise HTTPException(404, "Profile not found")
    return tutor_doc_to_model(d)


@api.patch("/tutors/me/profile", response_model=TutorProfile)
async def update_my_tutor_profile(patch: TutorProfileUpdate, u: dict = Depends(current_user)):
    if u["role"] != "tutor":
        raise HTTPException(403, "Only tutors")
    prev = await db.tutors.find_one({"user_id": u["id"]}, {"_id": 0})
    update = {k: v for k, v in patch.model_dump(exclude_none=True).items()}
    # Handle multi-location: geocode each and store as list of {name, lat, lng}.
    if "locations" in update:
        raw = [s.strip() for s in update["locations"] if s and s.strip()]
        prev_locs = {(l.get("name") or "").strip().lower(): l for l in (prev or {}).get("locations", [])}
        geocoded = []
        for name in raw:
            existing = prev_locs.get(name.strip().lower())
            if existing and existing.get("latitude") is not None:
                geocoded.append({"name": name, "latitude": existing["latitude"], "longitude": existing["longitude"]})
            else:
                coords = await run_in_threadpool(geocode, name)
                geocoded.append({"name": name, "latitude": (coords or {}).get("latitude"), "longitude": (coords or {}).get("longitude")})
        update["locations"] = geocoded
        # Sync primary legacy fields for the map/list card.
        if geocoded:
            update["location"] = geocoded[0]["name"]
            update["latitude"] = geocoded[0]["latitude"]
            update["longitude"] = geocoded[0]["longitude"]
    # Normalize weekly_availability: whitelist keys + normalize slots.
    if "weekly_availability" in update:
        wa_raw = update["weekly_availability"] or {}
        wa: dict = {}
        for day in WEEKDAYS:
            slots = wa_raw.get(day) if isinstance(wa_raw, dict) else None
            if isinstance(slots, list):
                clean = sorted({_normalize_slot(s) for s in slots if _normalize_slot(s)})
                if clean:
                    wa[day] = clean
        update["weekly_availability"] = wa
    if update:
        await db.tutors.update_one({"user_id": u["id"]}, {"$set": update})
        if "avatar_url" in update:
            await db.users.update_one({"id": u["id"]}, {"$set": {"avatar_url": update["avatar_url"]}})
    d = await db.tutors.find_one({"user_id": u["id"]}, {"_id": 0})
    return tutor_doc_to_model(d)


@api.get("/tutors/{tutor_id}/booked-slots")
async def tutor_booked_slots(tutor_id: str, start: Optional[str] = None, end: Optional[str] = None):
    """Return the tutor's non-canceled booked slots as [{date, time}]."""
    q: dict = {"tutor_id": tutor_id, "payment_status": {"$ne": "canceled"}}
    if start:
        q["date"] = {"$gte": start}
    if end:
        q.setdefault("date", {})["$lte"] = end
    rows = await db.bookings.find(q, {"_id": 0, "date": 1, "time": 1}).to_list(1000)
    return [{"date": r["date"], "time": _normalize_slot(r["time"])} for r in rows]


# ---- Bookings ----
@api.post("/bookings", response_model=Booking)
async def create_booking(body: BookingCreate, u: dict = Depends(current_user)):
    if u["role"] != "parent":
        raise HTTPException(403, "Only parents can book")
    t = await db.tutors.find_one({"id": body.tutor_id}, {"_id": 0})
    if not t:
        raise HTTPException(404, "Tutor not found")
    p = await db.parents.find_one({"user_id": u["id"]}, {"_id": 0}) or {}
    remote = bool(t.get("allows_remote"))
    au_pair = bool(body.is_au_pair)
    # Distance to CLOSEST tutor location.
    distance: Optional[float] = None
    if p.get("latitude") is not None:
        candidates: List[tuple] = []
        for loc in (t.get("locations") or []):
            if loc.get("latitude") is not None:
                candidates.append((loc["latitude"], loc["longitude"]))
        if not candidates and t.get("latitude") is not None:
            candidates.append((t["latitude"], t["longitude"]))
        if candidates:
            distance = round(
                min(haversine_miles(lat, lng, p["latitude"], p["longitude"]) for lat, lng in candidates),
                1,
            )
    # Rule enforcement
    if au_pair:
        if body.lessons_count < 30:
            raise HTTPException(400, "Au-pair bookings require a minimum of 30 lessons")
    else:
        if not remote:
            if distance is None:
                raise HTTPException(
                    400,
                    "Please set your city in your family profile so we can verify you're within 100 miles of this tutor.",
                )
            if distance > 100:
                raise HTTPException(
                    400,
                    f"This tutor is {distance} miles away — over the 100-mile limit for in-person lessons. Book them for remote lessons or an au-pair stay instead.",
                )
    lessons = max(1, body.lessons_count)
    base_amount = ((t["hourly_rate_cents"] * body.duration_minutes + 59) // 60) * lessons
    fee = platform_fee_for(base_amount)
    amount = base_amount + fee  # what the parent actually pays
    currency = t.get("currency", "usd")
    # Slot availability check: don't allow booking outside tutor's weekly availability
    # or over an existing booking. Skipped for au-pair (long-form stays).
    if not au_pair:
        if not is_slot_allowed(t, body.date, body.time):
            raise HTTPException(400, "This tutor isn't available at that time. Pick another slot.")
        if await is_slot_booked(t["id"], body.date, body.time):
            raise HTTPException(409, "That slot was just booked by someone else. Please pick another time.")
    booking_id = str(uuid.uuid4())
    booking = {
        "id": booking_id,
        "parent_id": u["id"],
        "parent_name": u["name"],
        "tutor_id": t["id"],
        "tutor_name": t["name"],
        "date": body.date,
        "time": body.time,
        "duration_minutes": body.duration_minutes,
        "language": body.language,
        "amount_cents": amount,
        "platform_fee_cents": fee,
        "currency": currency,
        "payment_status": "pending",
        "stripe_payment_intent_id": None,
        "client_secret": None,
        "notes": body.notes or "",
        "is_au_pair": au_pair,
        "lessons_count": lessons,
        "distance_miles": distance,
        "remote": remote and not au_pair,
        "housing_offered": (body.housing_offered or "").strip() if au_pair else "",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    # Create Stripe PaymentIntent
    try:
        intent = await run_in_threadpool(
            lambda: stripe.PaymentIntent.create(
                amount=amount,
                currency=currency,
                automatic_payment_methods={"enabled": True},
                metadata={"booking_id": booking_id},
                idempotency_key=f"booking-{booking_id}",
            )
        )
        booking["stripe_payment_intent_id"] = intent.id
        booking["client_secret"] = intent.client_secret
    except Exception as e:
        logger.warning(f"Stripe PaymentIntent failed: {e}. Falling back to mock.")
        booking["stripe_payment_intent_id"] = f"pi_mock_{booking_id}"
        booking["client_secret"] = f"pi_mock_secret_{booking_id}"
    await db.bookings.insert_one(booking)
    return Booking(**booking)


@api.post("/bookings/{booking_id}/confirm-mock", response_model=Booking)
async def confirm_mock(booking_id: str, u: dict = Depends(current_user)):
    """MOCKED payment confirmation — for MVP dev/preview only.

    Gated by env `ENABLE_MOCK_CONFIRM`. In production this MUST be `false` and
    `payment_status` should only be flipped by the signed Stripe webhook. Both
    settings live in `backend/.env`."""
    if os.getenv("ENABLE_MOCK_CONFIRM", "true").lower() != "true":
        raise HTTPException(410, "Mock payment confirmation is disabled in this environment.")
    b = await db.bookings.find_one({"id": booking_id}, {"_id": 0})
    if not b:
        raise HTTPException(404, "Booking not found")
    if b["parent_id"] != u["id"]:
        raise HTTPException(403, "Not your booking")
    await db.bookings.update_one({"id": booking_id}, {"$set": {"payment_status": "paid"}})
    b["payment_status"] = "paid"
    await credit_platform_fee(b)
    await push_notification(b["tutor_id"], "booking", "New booking confirmed", f"{b['parent_name']} booked {b['date']} at {b['time']}")
    await push_notification(b["parent_id"], "booking", "Booking confirmed", f"You're set with {b['tutor_name']} on {b['date']}")
    return Booking(**b)


@api.get("/bookings/me", response_model=List[Booking])
async def my_bookings(u: dict = Depends(current_user)):
    field = "parent_id" if u["role"] == "parent" else "tutor_id"
    docs = await db.bookings.find({field: u["id"]}, {"_id": 0}).sort("created_at", -1).to_list(200)
    return [Booking(**d) for d in docs]


@api.get("/bookings/{booking_id}", response_model=Booking)
async def get_booking(booking_id: str, u: dict = Depends(current_user)):
    b = await db.bookings.find_one({"id": booking_id}, {"_id": 0})
    if not b:
        raise HTTPException(404, "Booking not found")
    if b["parent_id"] != u["id"] and b["tutor_id"] != u["id"] and not u.get("is_admin"):
        raise HTTPException(403, "Not your booking")
    return Booking(**b)


@api.post("/stripe/webhook")
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
    obj = event["data"]["object"]
    intent_id = obj.get("id")
    status_map = {
        "payment_intent.succeeded": "paid",
        "payment_intent.payment_failed": "failed",
        "payment_intent.canceled": "canceled",
    }
    new_status = status_map.get(event["type"])
    if new_status and intent_id:
        await db.bookings.update_one(
            {"stripe_payment_intent_id": intent_id},
            {"$set": {"payment_status": new_status}},
        )
        if new_status == "paid":
            paid = await db.bookings.find_one({"stripe_payment_intent_id": intent_id}, {"_id": 0})
            if paid:
                await credit_platform_fee(paid)
    return {"received": True}


# ---- Messages ----
@api.post("/messages", response_model=Message)
async def send_message(body: MessageCreate, u: dict = Depends(current_user)):
    if not (await db.users.find_one({"id": body.to_user_id})):
        raise HTTPException(404, "Recipient not found")
    mid = str(uuid.uuid4())
    m = {
        "id": mid,
        "from_user_id": u["id"],
        "to_user_id": body.to_user_id,
        "text": body.text,
        "kind": "text",
        "invitation": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.messages.insert_one(m)
    await push_notification(body.to_user_id, "chat", f"New message from {u['name']}", body.text[:120])
    return Message(**m)


@api.post("/messages/invitation", response_model=Message)
async def send_invitation(body: InvitationCreate, u: dict = Depends(current_user)):
    if u["role"] != "tutor":
        raise HTTPException(403, "Only tutors can send lesson invitations")
    if not (await db.users.find_one({"id": body.to_user_id})):
        raise HTTPException(404, "Recipient not found")
    # Validate that the tutor isn't inviting outside their own calendar / on top of a booking.
    my_tutor = await db.tutors.find_one({"user_id": u["id"]}, {"_id": 0})
    if my_tutor:
        if not is_slot_allowed(my_tutor, body.date, body.time):
            raise HTTPException(400, "That slot is outside your weekly availability. Update it in your profile or pick another time.")
        if await is_slot_booked(my_tutor["id"], body.date, body.time):
            raise HTTPException(409, "You already have a booking at that time.")
    mid = str(uuid.uuid4())
    inv = {
        "price_cents": body.price_cents, "date": body.date, "time": body.time,
        "duration_minutes": body.duration_minutes, "language": body.language,
        "note": body.note or "", "status": "pending", "booking_id": None,
    }
    m = {
        "id": mid,
        "from_user_id": u["id"],
        "to_user_id": body.to_user_id,
        "text": f"Lesson invitation · {body.language} · {body.date} {body.time}",
        "kind": "invitation",
        "invitation": inv,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.messages.insert_one(m)
    await push_notification(body.to_user_id, "invitation", f"Lesson invitation from {u['name']}", f"{body.language} · {body.date} at {body.time} · ${body.price_cents/100:.0f}")
    return Message(**m)


@api.post("/messages/invitation/{message_id}/accept", response_model=Booking)
async def accept_invitation(message_id: str, u: dict = Depends(current_user)):
    if u["role"] != "parent":
        raise HTTPException(403, "Only parents can accept invitations")
    msg = await db.messages.find_one({"id": message_id}, {"_id": 0})
    if not msg or msg.get("kind") != "invitation":
        raise HTTPException(404, "Invitation not found")
    if msg["to_user_id"] != u["id"]:
        raise HTTPException(403, "Not your invitation")
    inv = msg.get("invitation") or {}
    if inv.get("status") != "pending":
        raise HTTPException(400, f"Invitation is already {inv.get('status')}")
    t = await db.tutors.find_one({"user_id": msg["from_user_id"]}, {"_id": 0})
    if not t:
        raise HTTPException(404, "Tutor profile not found")
    # Guard against double-booking during the pending window.
    if await is_slot_booked(t["id"], inv["date"], inv["time"]):
        raise HTTPException(409, "That slot is no longer available.")
    booking_id = str(uuid.uuid4())
    inv_base = int(inv["price_cents"])
    inv_fee = platform_fee_for(inv_base)
    inv_total = inv_base + inv_fee
    booking = {
        "id": booking_id,
        "parent_id": u["id"],
        "parent_name": u["name"],
        "tutor_id": t["id"],
        "tutor_name": t["name"],
        "date": inv["date"],
        "time": inv["time"],
        "duration_minutes": inv["duration_minutes"],
        "language": inv["language"],
        "amount_cents": inv_total,
        "platform_fee_cents": inv_fee,
        "currency": t.get("currency", "usd"),
        "payment_status": "pending",
        "stripe_payment_intent_id": None,
        "client_secret": None,
        "notes": inv.get("note", ""),
        "is_au_pair": False,
        "lessons_count": 1,
        "distance_miles": None,
        "remote": bool(t.get("allows_remote")),
        "housing_offered": "",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    # Stripe PaymentIntent (best-effort)
    try:
        intent = await run_in_threadpool(
            lambda: stripe.PaymentIntent.create(
                amount=inv_total, currency=booking["currency"],
                automatic_payment_methods={"enabled": True},
                metadata={"booking_id": booking_id, "invitation_message_id": message_id},
                idempotency_key=f"invitation-{booking_id}",
            )
        )
        booking["stripe_payment_intent_id"] = intent.id
        booking["client_secret"] = intent.client_secret
    except Exception:
        booking["stripe_payment_intent_id"] = f"pi_mock_{booking_id}"
        booking["client_secret"] = f"pi_mock_secret_{booking_id}"
    await db.bookings.insert_one(booking)
    await db.messages.update_one(
        {"id": message_id},
        {"$set": {"invitation.status": "accepted", "invitation.booking_id": booking_id}},
    )
    await push_notification(t["user_id"], "booking", "Invitation accepted", f"{u['name']} accepted your lesson invitation for {inv['date']}")
    return Booking(**booking)


@api.post("/messages/invitation/{message_id}/decline")
async def decline_invitation(message_id: str, u: dict = Depends(current_user)):
    msg = await db.messages.find_one({"id": message_id}, {"_id": 0})
    if not msg or msg.get("kind") != "invitation":
        raise HTTPException(404, "Invitation not found")
    if msg["to_user_id"] != u["id"]:
        raise HTTPException(403, "Not your invitation")
    await db.messages.update_one({"id": message_id}, {"$set": {"invitation.status": "declined"}})
    return {"declined": True}


@api.get("/tutors/by-user/{user_id}", response_model=TutorProfile)
async def tutor_by_user(user_id: str):
    d = await db.tutors.find_one({"user_id": user_id}, {"_id": 0})
    if not d:
        raise HTTPException(404, "Tutor profile not found")
    return tutor_doc_to_model(d)


@api.get("/messages/threads")
async def get_threads(u: dict = Depends(current_user)):
    pipeline = [
        {"$match": {"$or": [{"from_user_id": u["id"]}, {"to_user_id": u["id"]}]}},
        {"$sort": {"created_at": -1}},
    ]
    docs = await db.messages.aggregate(pipeline).to_list(1000)
    seen: dict = {}
    for d in docs:
        other = d["to_user_id"] if d["from_user_id"] == u["id"] else d["from_user_id"]
        if other in seen:
            continue
        seen[other] = {"other_user_id": other, "last_message": d["text"], "created_at": d["created_at"]}
    # attach user info
    result = []
    for other, info in seen.items():
        user = await db.users.find_one({"id": other}, {"_id": 0, "password_hash": 0})
        if user:
            info["other_user_name"] = user["name"]
            info["other_user_avatar"] = user.get("avatar_url")
            info["other_user_role"] = user["role"]
        result.append(info)
    result.sort(key=lambda x: x["created_at"], reverse=True)
    return result


@api.get("/messages/thread/{other_user_id}", response_model=List[Message])
async def get_thread(other_user_id: str, u: dict = Depends(current_user)):
    docs = await db.messages.find(
        {"$or": [
            {"from_user_id": u["id"], "to_user_id": other_user_id},
            {"from_user_id": other_user_id, "to_user_id": u["id"]},
        ]},
        {"_id": 0},
    ).sort("created_at", 1).to_list(500)
    return [Message(**d) for d in docs]


# ---- Reviews ----
@api.post("/reviews", response_model=Review)
async def create_review(body: ReviewCreate, u: dict = Depends(current_user)):
    if u["role"] != "parent":
        raise HTTPException(403, "Only parents can review")
    if not (await db.tutors.find_one({"id": body.tutor_id})):
        raise HTTPException(404, "Tutor not found")
    rid = str(uuid.uuid4())
    r = {
        "id": rid,
        "tutor_id": body.tutor_id,
        "booking_id": body.booking_id,
        "parent_id": u["id"],
        "parent_name": u["name"],
        "rating": body.rating,
        "comment": body.comment,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.reviews.insert_one(r)
    # Recompute rating
    all_reviews = await db.reviews.find({"tutor_id": body.tutor_id}, {"_id": 0}).to_list(1000)
    avg = sum(x["rating"] for x in all_reviews) / len(all_reviews)
    await db.tutors.update_one(
        {"id": body.tutor_id},
        {"$set": {"rating": round(avg, 2), "reviews_count": len(all_reviews)}},
    )
    return Review(**r)


@api.get("/reviews/tutor/{tutor_id}", response_model=List[Review])
async def tutor_reviews(tutor_id: str):
    docs = await db.reviews.find({"tutor_id": tutor_id}, {"_id": 0}).sort("created_at", -1).to_list(200)
    return [Review(**d) for d in docs]


# ---- W-9 tax forms ----
def _mask_tin(t: str) -> str:
    digits = "".join(ch for ch in (t or "") if ch.isdigit())
    if len(digits) < 4:
        return "•" * len(digits)
    return "•" * (len(digits) - 4) + digits[-4:]


def w9_public(doc: dict) -> W9Form:
    """Strip encrypted TIN before returning to any caller."""
    safe = {k: v for k, v in doc.items() if k not in ("tin_encrypted", "_id")}
    return W9Form(**safe)


async def tutor_has_completed_session(user_id: str) -> Optional[dict]:
    """Return the earliest completed paid booking for this tutor (or None)."""
    tutor = await db.tutors.find_one({"user_id": user_id}, {"_id": 0, "id": 1})
    if not tutor:
        return None
    now = datetime.now(timezone.utc)
    docs = await db.bookings.find(
        {"tutor_id": tutor["id"], "payment_status": "paid"},
        {"_id": 0}
    ).sort("date", 1).to_list(200)
    for b in docs:
        try:
            dt = datetime.fromisoformat(f"{b['date']}T{b['time']}:00+00:00")
        except Exception:
            continue
        end = dt + timedelta(minutes=int(b.get("duration_minutes") or 60))
        if end < now:
            return b
    return None


@api.post("/w9", response_model=W9Form, status_code=201)
async def submit_w9(body: W9FormIn, u: dict = Depends(current_user)):
    if u.get("role") != "tutor":
        raise HTTPException(403, "Only tutors submit W-9 forms")
    valid = {"individual", "sole_proprietor", "c_corp", "s_corp", "partnership", "trust_estate", "llc", "other"}
    if body.tax_classification not in valid:
        raise HTTPException(422, "Invalid federal tax classification")
    if body.tin_type not in ("ssn", "ein"):
        raise HTTPException(422, "tin_type must be 'ssn' or 'ein'")
    tin_digits = "".join(ch for ch in body.tin if ch.isdigit())
    if body.tin_type == "ssn" and len(tin_digits) != 9:
        raise HTTPException(422, "SSN must be 9 digits")
    if body.tin_type == "ein" and len(tin_digits) != 9:
        raise HTTPException(422, "EIN must be 9 digits")

    now_iso = datetime.now(timezone.utc).isoformat()
    existing = await db.w9_forms.find_one({"tutor_user_id": u["id"]})
    doc = {
        "id": (existing or {}).get("id") or str(uuid.uuid4()),
        "tutor_user_id": u["id"],
        "tutor_name": u["name"],
        "tutor_email": u["email"],
        "legal_name": body.legal_name.strip(),
        "business_name": (body.business_name or "").strip(),
        "tax_classification": body.tax_classification,
        "llc_tax_class": (body.llc_tax_class or "").upper() if body.tax_classification == "llc" else "",
        "other_classification": (body.other_classification or "").strip() if body.tax_classification == "other" else "",
        "address": body.address.strip(),
        "city": body.city.strip(),
        "state": body.state.strip(),
        "zip_code": body.zip_code.strip(),
        "country": (body.country or "US").strip(),
        "tin_type": body.tin_type,
        "tin_masked": _mask_tin(tin_digits),
        # Fernet-encrypted TIN. Rotates via W9_ENCRYPTION_KEYS. Never returned by the API.
        "tin_encrypted": encrypt_tin(tin_digits),
        "signature_name": body.signature_name.strip(),
        "is_us_person": bool(body.is_us_person),
        "exempt_from_backup": bool(body.exempt_from_backup),
        "signed_at": (existing or {}).get("signed_at") or now_iso,
        "updated_at": now_iso,
    }
    await db.w9_forms.update_one({"tutor_user_id": u["id"]}, {"$set": doc}, upsert=True)
    # Mark any pending w9-required notifications as read.
    await db.notifications.update_many(
        {"user_id": u["id"], "kind": {"$regex": "^w9:"}},
        {"$set": {"read": True}},
    )
    return w9_public(doc)


@api.get("/w9/me", response_model=Optional[W9Form])
async def my_w9(u: dict = Depends(current_user)):
    if u.get("role") != "tutor":
        raise HTTPException(403, "Only tutors have W-9 forms")
    doc = await db.w9_forms.find_one({"tutor_user_id": u["id"]}, {"_id": 0})
    return w9_public(doc) if doc else None


@api.get("/w9/me/status")
async def my_w9_status(u: dict = Depends(current_user)):
    """Lightweight status endpoint used by the tutor UI to decide whether to nudge the tutor."""
    if u.get("role") != "tutor":
        return {"required": False, "submitted": False, "completed_session": False}
    submitted = bool(await db.w9_forms.find_one({"tutor_user_id": u["id"]}, {"_id": 0, "id": 1}))
    first_completed = await tutor_has_completed_session(u["id"])
    return {
        "required": bool(first_completed) and not submitted,
        "submitted": submitted,
        "completed_session": bool(first_completed),
        "first_booking_id": (first_completed or {}).get("id"),
    }


@api.get("/admin/w9", response_model=List[W9Form])
async def admin_list_w9(u: dict = Depends(require_admin), limit: int = 200):
    docs = await db.w9_forms.find({}, {"_id": 0}).sort("updated_at", -1).to_list(limit)
    return [w9_public(d) for d in docs]


@api.get("/admin/w9/{tutor_user_id}", response_model=W9Form)
async def admin_get_w9(tutor_user_id: str, u: dict = Depends(require_admin)):
    doc = await db.w9_forms.find_one({"tutor_user_id": tutor_user_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "W-9 not found for that tutor")
    return w9_public(doc)


@api.get("/admin/w9-encryption-status")
async def admin_w9_encryption_status(u: dict = Depends(require_admin)):
    """Ops endpoint: shows key config + counts of records under old vs primary key.
    Use during a rotation to know when it's safe to remove the retired key."""
    total = await db.w9_forms.count_documents({})
    primary = 0
    legacy = 0
    async for doc in db.w9_forms.find({}, {"_id": 0, "tin_encrypted": 1}):
        token = (doc or {}).get("tin_encrypted") or ""
        try:
            _fernets[0].decrypt(token.encode())
            primary += 1
        except InvalidToken:
            legacy += 1
    return {
        "keys_configured": len(_fernets),
        "ephemeral_key": _EPHEMERAL_W9_KEY,
        "records_total": total,
        "records_on_primary_key": primary,
        "records_needing_rotation": legacy,
    }


# ---- Parent profile ----
def parent_doc_to_model(p: dict, name: str) -> ParentProfile:
    return ParentProfile(
        user_id=p["user_id"],
        name=p.get("name") or name,
        avatar_url=p.get("avatar_url"),
        city=p.get("city", ""),
        latitude=p.get("latitude"),
        longitude=p.get("longitude"),
        languages_desired=p.get("languages_desired", []),
        hours_per_week=p.get("hours_per_week", 5),
        learning_materials=p.get("learning_materials", ""),
        children=[Child(**c) for c in p.get("children", [])],
    )


@api.get("/parents/me/profile", response_model=ParentProfile)
async def get_parent_profile(u: dict = Depends(current_user)):
    if u["role"] != "parent":
        raise HTTPException(403, "Only parents")
    doc = await db.parents.find_one({"user_id": u["id"]}, {"_id": 0})
    if not doc:
        doc = {
            "user_id": u["id"], "name": u["name"], "avatar_url": u.get("avatar_url"),
            "city": "", "languages_desired": [], "hours_per_week": 5,
            "learning_materials": "", "children": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.parents.insert_one(dict(doc))
    return parent_doc_to_model(doc, u["name"])


@api.patch("/parents/me/profile", response_model=ParentProfile)
async def update_parent_profile(patch: ParentProfileUpdate, u: dict = Depends(current_user)):
    if u["role"] != "parent":
        raise HTTPException(403, "Only parents")
    prev = await db.parents.find_one({"user_id": u["id"]}, {"_id": 0}) or {}
    update = patch.model_dump(exclude_none=True)
    if update.get("children") is not None and len(update["children"]) > 10:
        raise HTTPException(400, "Max 10 children")
    if update.get("children"):
        update["children"] = [c if isinstance(c, dict) else c.model_dump() for c in update["children"]]
    if update:
        await db.parents.update_one({"user_id": u["id"]}, {"$set": update}, upsert=True)
        if "name" in update or "avatar_url" in update:
            user_patch = {k: v for k, v in update.items() if k in ("name", "avatar_url")}
            await db.users.update_one({"id": u["id"]}, {"$set": user_patch})
        if "city" in update:
            await maybe_geocode_and_persist(db.parents, {"user_id": u["id"]}, update["city"], prev)
    doc = await db.parents.find_one({"user_id": u["id"]}, {"_id": 0})
    fresh = await db.users.find_one({"id": u["id"]}, {"_id": 0})
    return parent_doc_to_model(doc, fresh["name"] if fresh else u["name"])


@api.get("/parents/{user_id}/public", response_model=ParentProfile)
async def get_parent_public(user_id: str, u: dict = Depends(current_user)):
    """Public parent profile. Non-owners see children names + ages but NEVER their photos."""
    parent = await db.parents.find_one({"user_id": user_id}, {"_id": 0})
    if not parent:
        raise HTTPException(404, "Parent profile not found")
    fresh = await db.users.find_one({"id": user_id}, {"_id": 0})
    if not fresh:
        raise HTTPException(404, "User not found")
    is_owner = u["id"] == user_id
    if not is_owner:
        # Strip children avatars for non-owners.
        parent = dict(parent)
        parent["children"] = [
            {**c, "avatar_url": None} for c in parent.get("children", [])
        ]
    return parent_doc_to_model(parent, fresh["name"])


# ---- Favourites, events, notifications ----
class EventIn(BaseModel):
    name: str
    props: Optional[dict] = None


@api.post("/events")
async def track_event(body: EventIn, u: dict = Depends(current_user)):
    await db.events.insert_one({
        "user_id": u["id"], "role": u["role"], "user_name": u["name"], "name": body.name,
        "props": body.props or {}, "at": datetime.now(timezone.utc).isoformat(),
    })
    return {"ok": True}


@api.post("/favorites/{tutor_id}")
async def add_fav(tutor_id: str, u: dict = Depends(current_user)):
    if u["role"] != "parent":
        raise HTTPException(403, "Only parents")
    if not await db.tutors.find_one({"id": tutor_id}):
        raise HTTPException(404, "Tutor not found")
    await db.favorites.update_one(
        {"user_id": u["id"], "tutor_id": tutor_id},
        {"$set": {"user_id": u["id"], "tutor_id": tutor_id, "at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    return {"saved": True}


@api.delete("/favorites/{tutor_id}")
async def remove_fav(tutor_id: str, u: dict = Depends(current_user)):
    await db.favorites.delete_one({"user_id": u["id"], "tutor_id": tutor_id})
    return {"saved": False}


@api.get("/favorites")
async def list_favs(u: dict = Depends(current_user)):
    rows = await db.favorites.find({"user_id": u["id"]}, {"_id": 0, "tutor_id": 1}).to_list(500)
    return [r["tutor_id"] for r in rows]


class NotificationOut(BaseModel):
    id: str
    kind: str
    title: str
    body: str
    at: str
    read: bool = False


async def push_notification(user_id: str, kind: str, title: str, body: str):
    await db.notifications.insert_one({
        "id": str(uuid.uuid4()), "user_id": user_id, "kind": kind,
        "title": title, "body": body, "read": False,
        "at": datetime.now(timezone.utc).isoformat(),
    })


@api.get("/notifications", response_model=List[NotificationOut])
async def my_notifications(u: dict = Depends(current_user)):
    await _generate_dynamic_notifications(u)
    docs = await db.notifications.find({"user_id": u["id"]}, {"_id": 0}).sort("at", -1).to_list(50)
    return [NotificationOut(**d) for d in docs]


# ---- Admin analytics ----
@api.get("/admin/stats")
async def admin_stats(u: dict = Depends(require_admin)):
    total_fee_cents = 0
    async for row in db.platform_earnings.aggregate([
        {"$group": {"_id": None, "total": {"$sum": "$amount_cents"}}}
    ]):
        total_fee_cents = int(row.get("total") or 0)
    return {
        "users": await db.users.count_documents({}),
        "parents": await db.users.count_documents({"role": "parent"}),
        "tutors": await db.users.count_documents({"role": "tutor"}),
        "bookings": await db.bookings.count_documents({}),
        "paid_bookings": await db.bookings.count_documents({"payment_status": "paid"}),
        "messages": await db.messages.count_documents({}),
        "reviews": await db.reviews.count_documents({}),
        "favorites": await db.favorites.count_documents({}),
        "events": await db.events.count_documents({}),
        "platform_earnings_cents": total_fee_cents,
        "platform_earnings_count": await db.platform_earnings.count_documents({}),
    }


@api.get("/admin/earnings")
async def admin_earnings(u: dict = Depends(require_admin), limit: int = 50):
    docs = await db.platform_earnings.find({}, {"_id": 0}).sort("at", -1).to_list(limit)
    total_cents = 0
    async for row in db.platform_earnings.aggregate([
        {"$group": {"_id": None, "total": {"$sum": "$amount_cents"}}}
    ]):
        total_cents = int(row.get("total") or 0)
    return {"total_cents": total_cents, "count": await db.platform_earnings.count_documents({}), "entries": docs}


@api.get("/admin/events")
async def admin_events(u: dict = Depends(require_admin), limit: int = 100, name: Optional[str] = None):
    q: dict = {}
    if name:
        q["name"] = name
    docs = await db.events.find(q, {"_id": 0}).sort("at", -1).to_list(limit)
    # Aggregate by event name
    counts_pipeline = [
        {"$group": {"_id": "$name", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 20},
    ]
    counts = await db.events.aggregate(counts_pipeline).to_list(20)
    return {"events": docs, "counts": [{"name": c["_id"], "count": c["count"]} for c in counts]}


@api.get("/admin/users")
async def admin_users(u: dict = Depends(require_admin), limit: int = 100):
    docs = await db.users.find({}, {"_id": 0, "password_hash": 0}).sort("created_at", -1).to_list(limit)
    return docs


async def _generate_dynamic_notifications(u: dict):
    """Create morning-of, 2h-before, and post-session review notifications on demand."""
    now = datetime.now(timezone.utc)
    # W-9 nudge for tutors after their first completed paid session (once).
    if u["role"] == "tutor":
        submitted = await db.w9_forms.find_one({"tutor_user_id": u["id"]}, {"_id": 0, "id": 1})
        if not submitted:
            first_done = await tutor_has_completed_session(u["id"])
            if first_done:
                key = "w9:required"
                if not await db.notifications.find_one({"user_id": u["id"], "kind": key}):
                    await db.notifications.insert_one({
                        "id": str(uuid.uuid4()), "user_id": u["id"], "kind": key,
                        "title": "Complete your W-9 (US tax form)",
                        "body": "You've completed your first session — file a W-9 so we can pay you.",
                        "read": False, "at": now.isoformat(),
                    })
    # Reminders + review requests for parent's bookings
    if u["role"] == "parent":
        bookings = await db.bookings.find({"parent_id": u["id"], "payment_status": "paid"}, {"_id": 0}).to_list(200)
        for b in bookings:
            try:
                dt = datetime.fromisoformat(f"{b['date']}T{b['time']}:00+00:00")
            except Exception:
                continue
            delta_min = (dt - now).total_seconds() / 60
            # Morning-of reminder: fires once when the session is TODAY and still upcoming (delta > 10 min).
            same_day = dt.date() == now.date()
            if same_day and 10 < delta_min < 24 * 60:
                key = f"morning:{b['id']}"
                if not await db.notifications.find_one({"user_id": u["id"], "kind": key}):
                    await db.notifications.insert_one({
                        "id": str(uuid.uuid4()), "user_id": u["id"], "kind": key,
                        "title": f"Session today at {b['time']}",
                        "body": f"{b['tutor_name']} · {b['language']} · tap to get ready",
                        "read": False, "at": now.isoformat(),
                    })
            # 2-hour reminder (fires once when within 120 min and > -30 min)
            if -30 < delta_min < 120:
                key = f"reminder:{b['id']}"
                if not await db.notifications.find_one({"user_id": u["id"], "kind": key}):
                    await db.notifications.insert_one({
                        "id": str(uuid.uuid4()), "user_id": u["id"], "kind": key,
                        "title": "Session in 2 hours",
                        "body": f"{b['tutor_name']} at {b['time']} · {b['language']}",
                        "read": False, "at": now.isoformat(),
                    })
            # Review request 30+ min after session ended
            end_min = delta_min - b.get("duration_minutes", 60)
            if end_min < -30 and not await db.reviews.find_one({"booking_id": b["id"]}):
                key = f"review:{b['id']}"
                if not await db.notifications.find_one({"user_id": u["id"], "kind": key}):
                    await db.notifications.insert_one({
                        "id": str(uuid.uuid4()), "user_id": u["id"], "kind": key,
                        "title": "How was your session?",
                        "body": f"Rate {b['tutor_name']} and help other families.",
                        "read": False, "at": now.isoformat(),
                    })


@api.post("/notifications/read-all")
async def read_all(u: dict = Depends(current_user)):
    await db.notifications.update_many({"user_id": u["id"]}, {"$set": {"read": True}})
    return {"ok": True}


# ---- Delete account ----
@api.delete("/auth/me")
async def delete_account(u: dict = Depends(current_user)):
    uid = u["id"]
    if u["role"] == "tutor":
        await db.tutors.delete_many({"user_id": uid})
        await db.w9_forms.delete_many({"tutor_user_id": uid})
    else:
        await db.parents.delete_many({"user_id": uid})
    await db.bookings.delete_many({"$or": [{"parent_id": uid}, {"tutor_id": uid}]})
    await db.messages.delete_many({"$or": [{"from_user_id": uid}, {"to_user_id": uid}]})
    await db.reviews.delete_many({"parent_id": uid})
    # Ancillary PII: purge everything else tied to this account.
    await db.notifications.delete_many({"user_id": uid})
    await db.events.delete_many({"user_id": uid})
    await db.favorites.delete_many({"user_id": uid})
    await db.uploads.delete_many({"owner_id": uid})
    # Platform earnings intentionally preserved (accounting record); no PII lives on that doc.
    await db.users.delete_one({"id": uid})
    return {"deleted": True}


# ---- Seed ----
SEED_TUTORS = [
    {
        "name": "Sofía García", "email": "sofia@babybabel.dev",
        "bio": "Bilingual educator with 8 years of experience helping children fall in love with Spanish through play, songs, and stories.",
        "languages": ["Spanish", "English"], "hourly_rate_cents": 3500, "location": "Barcelona, ES",
        "latitude": 41.3874, "longitude": 2.1686, "allows_remote": True,
        "experience_years": 8, "rating": 4.9, "reviews_count": 42,
        "avatar_url": "https://images.pexels.com/photos/38808650/pexels-photo-38808650.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=650&w=940",
        "hero_image_url": "https://images.unsplash.com/photo-1583468982228-19f19164aee2?crop=entropy&cs=srgb&fm=jpg&q=85&w=1200",
        "accreditation_urls": ["https://images.unsplash.com/photo-1589330694653-ded6df03f754?crop=entropy&cs=srgb&fm=jpg&q=85&w=800"],
    },
    {
        "name": "Marie Dubois", "email": "marie@babybabel.dev",
        "bio": "Certified French tutor and childcare specialist. I turn every session into a little Parisian adventure.",
        "languages": ["French", "English"], "hourly_rate_cents": 4200, "location": "Lyon, FR",
        "latitude": 45.7640, "longitude": 4.8357, "allows_remote": False,
        "experience_years": 12, "rating": 4.8, "reviews_count": 67,
        "avatar_url": "https://images.unsplash.com/photo-1573497019940-1c28c88b4f3e?crop=entropy&cs=srgb&fm=jpg&q=85&w=800",
        "hero_image_url": "https://images.unsplash.com/photo-1503454537195-1dcabb73ffb9?crop=entropy&cs=srgb&fm=jpg&q=85&w=1200",
        "accreditation_urls": [],
    },
]

KEEP_EMAILS = {t["email"] for t in SEED_TUTORS}


async def seed_data():
    admin_email = "copperstone17@gmail.com"
    admin_pw = os.environ.get("ADMIN_INITIAL_PASSWORD")
    if not admin_pw:
        logger.warning("ADMIN_INITIAL_PASSWORD not set — admin seed skipped")
    admin = await db.users.find_one({"email": admin_email})
    if not admin and admin_pw:
        await db.users.insert_one({
            "id": str(uuid.uuid4()), "email": admin_email,
            "password_hash": hash_password(admin_pw),
            "name": "Babybabel Admin", "role": "admin", "avatar_url": None,
            "is_admin": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    elif admin and not admin.get("is_admin"):
        await db.users.update_one({"email": admin_email}, {"$set": {"is_admin": True, "role": "admin"}})
    # Only remove legacy DEMO tutors (emails on the @babybabel.dev domain) that aren't in the keep list.
    # NEVER touch real tutor signups.
    legacy_users = await db.users.find(
        {"role": "tutor", "email": {"$regex": "@babybabel\\.dev$", "$nin": list(KEEP_EMAILS)}},
        {"_id": 0, "id": 1},
    ).to_list(500)
    for lu in legacy_users:
        await db.tutors.delete_many({"user_id": lu["id"]})
        await db.users.delete_one({"id": lu["id"]})
    logger.info("Seeding sample tutors…")
    for t in SEED_TUTORS:
        if await db.users.find_one({"email": t["email"]}):
            continue
        uid = str(uuid.uuid4())
        tid = str(uuid.uuid4())
        udoc = {
            "id": uid, "email": t["email"], "password_hash": hash_password("password123"),
            "name": t["name"], "role": "tutor", "avatar_url": t["avatar_url"],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.users.insert_one(udoc)
        tdoc = {
            "id": tid, "user_id": uid, "name": t["name"], "avatar_url": t["avatar_url"],
            "bio": t["bio"], "languages": t["languages"], "hourly_rate_cents": t["hourly_rate_cents"],
            "currency": "usd", "location": t["location"], "experience_years": t["experience_years"],
            "latitude": t.get("latitude"), "longitude": t.get("longitude"), "allows_remote": t.get("allows_remote", False),
            "rating": t["rating"], "reviews_count": t["reviews_count"],
            "accreditation_urls": t["accreditation_urls"], "hero_image_url": t["hero_image_url"],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.tutors.insert_one(tdoc)


@app.on_event("startup")
async def on_startup():
    await db.users.create_index("email", unique=True)
    await db.tutors.create_index("user_id")
    await db.bookings.create_index("parent_id")
    await db.bookings.create_index("tutor_id")
    await db.messages.create_index([("from_user_id", 1), ("to_user_id", 1)])
    await db.w9_forms.create_index("tutor_user_id", unique=True)
    try:
        if EMERGENT_KEY:
            await run_in_threadpool(_init_storage_sync)
            logger.info("Object storage initialized")
    except Exception as e:
        logger.warning(f"Storage init deferred: {e}")
    await seed_data()
    await _migrate_w9_tins()


async def _migrate_w9_tins() -> None:
    """One-shot: re-encrypt any W-9 TINs that were stored with the legacy base64 scheme
    (or with an old Fernet key that's since rotated out). Idempotent — a Fernet-native
    token under the current primary key is left alone."""
    migrated = 0
    failed = 0
    cursor = db.w9_forms.find({"tin_encrypted": {"$ne": None}}, {"_id": 0, "tutor_user_id": 1, "tin_encrypted": 1})
    async for doc in cursor:
        token = doc.get("tin_encrypted") or ""
        # Skip fresh Fernet tokens under the current primary key.
        try:
            _fernets[0].decrypt(token.encode())
            continue
        except InvalidToken:
            pass
        plain = decrypt_tin(token)
        if not plain:
            failed += 1
            continue
        await db.w9_forms.update_one(
            {"tutor_user_id": doc["tutor_user_id"]},
            {"$set": {"tin_encrypted": encrypt_tin(plain)}},
        )
        migrated += 1
    if migrated or failed:
        logger.info(f"W-9 TIN migration: re-encrypted {migrated} record(s), {failed} failed.")


@api.get("/")
async def root():
    return {"app": "Babybabel", "status": "ok"}


app.include_router(api)


@app.on_event("shutdown")
async def shutdown():
    client.close()
