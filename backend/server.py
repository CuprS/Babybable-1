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
import time
import threading

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

# ---- Config ----
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
JWT_SECRET = os.environ["JWT_SECRET"]
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


# ---- Models ----
Role = Literal["parent", "tutor", "admin"]


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=72)
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


class BookingCreate(BaseModel):
    tutor_id: str
    date: str
    time: str
    duration_minutes: int = Field(gt=0, le=480)
    language: str
    notes: Optional[str] = ""
    is_au_pair: bool = False
    lessons_count: int = Field(default=1, ge=1, le=200)


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
    currency: str
    payment_status: str
    stripe_payment_intent_id: Optional[str] = None
    client_secret: Optional[str] = None
    notes: Optional[str] = ""
    is_au_pair: bool = False
    lessons_count: int = 1
    distance_miles: Optional[float] = None
    remote: bool = False
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


def user_to_public(u: dict) -> UserPublic:
    return UserPublic(id=u["id"], email=u["email"], name=u["name"], role=u["role"], avatar_url=u.get("avatar_url"), is_admin=bool(u.get("is_admin")))


async def require_admin(u: dict = Depends(current_user)) -> dict:
    if not u.get("is_admin"):
        raise HTTPException(403, "Admin only")
    return u


# ---- Auth routes ----
@api.post("/auth/signup", response_model=AuthResponse, status_code=201)
async def signup(body: SignupRequest):
    email = body.email.lower().strip()
    existing = await db.users.find_one({"email": email})
    if existing:
        raise HTTPException(409, "Email already registered")
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
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    return AuthResponse(access_token=make_token(uid, body.role), user=user_to_public(doc))


@api.post("/auth/login", response_model=AuthResponse)
async def login(body: LoginRequest):
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
async def get_file(path: str):
    # Public read for images. Ownership check lives in DB record (we just serve).
    rec = await db.uploads.find_one({"path": path}, {"_id": 0})
    if not rec:
        raise HTTPException(404, "File not found")
    try:
        content, ctype = await run_in_threadpool(_get_object_sync, path)
    except Exception as e:
        logger.exception("download failed")
        raise HTTPException(502, f"Download failed: {e}")
    return Response(content=content, media_type=ctype, headers={"Cache-Control": "public, max-age=86400"})


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
async def list_tutors(q: Optional[str] = None, language: Optional[str] = None, min_rate: Optional[int] = None, max_rate: Optional[int] = None):
    query: dict = {}
    if language:
        query["languages"] = {"$regex": f"^{language}$", "$options": "i"}
    if min_rate is not None:
        query.setdefault("hourly_rate_cents", {})["$gte"] = min_rate
    if max_rate is not None:
        query.setdefault("hourly_rate_cents", {})["$lte"] = max_rate
    if q:
        query["$or"] = [
            {"name": {"$regex": q, "$options": "i"}},
            {"bio": {"$regex": q, "$options": "i"}},
            {"location": {"$regex": q, "$options": "i"}},
            {"languages": {"$regex": q, "$options": "i"}},
        ]
    docs = await db.tutors.find(query, {"_id": 0}).to_list(200)
    return [tutor_doc_to_model(d) for d in docs]


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
    if update:
        await db.tutors.update_one({"user_id": u["id"]}, {"$set": update})
        if "avatar_url" in update:
            await db.users.update_one({"id": u["id"]}, {"$set": {"avatar_url": update["avatar_url"]}})
    d = await db.tutors.find_one({"user_id": u["id"]}, {"_id": 0})
    return tutor_doc_to_model(d)


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
    amount = ((t["hourly_rate_cents"] * body.duration_minutes + 59) // 60) * lessons
    currency = t.get("currency", "usd")
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
        "currency": currency,
        "payment_status": "pending",
        "stripe_payment_intent_id": None,
        "client_secret": None,
        "notes": body.notes or "",
        "is_au_pair": au_pair,
        "lessons_count": lessons,
        "distance_miles": distance,
        "remote": remote and not au_pair,
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
    """MOCKED payment confirmation — for MVP without native Stripe SDK in Expo Go."""
    b = await db.bookings.find_one({"id": booking_id}, {"_id": 0})
    if not b:
        raise HTTPException(404, "Booking not found")
    if b["parent_id"] != u["id"]:
        raise HTTPException(403, "Not your booking")
    await db.bookings.update_one({"id": booking_id}, {"$set": {"payment_status": "paid"}})
    b["payment_status"] = "paid"
    await push_notification(b["tutor_id"], "booking", "New booking confirmed", f"{b['parent_name']} booked {b['date']} at {b['time']}")
    await push_notification(b["parent_id"], "booking", "Booking confirmed", f"You're set with {b['tutor_name']} on {b['date']}")
    return Booking(**b)


@api.get("/bookings/me", response_model=List[Booking])
async def my_bookings(u: dict = Depends(current_user)):
    field = "parent_id" if u["role"] == "parent" else "tutor_id"
    docs = await db.bookings.find({field: u["id"]}, {"_id": 0}).sort("created_at", -1).to_list(200)
    return [Booking(**d) for d in docs]


@api.post("/stripe/webhook")
async def stripe_webhook(request: Request, stripe_signature: str = Header(None, alias="Stripe-Signature")):
    payload = await request.body()
    secret = os.environ.get("STRIPE_WEBHOOK_SECRET")
    try:
        if secret:
            event = stripe.Webhook.construct_event(payload, stripe_signature, secret)
        else:
            import json
            event = json.loads(payload)
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
    booking_id = str(uuid.uuid4())
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
        "amount_cents": inv["price_cents"],
        "currency": t.get("currency", "usd"),
        "payment_status": "pending",
        "stripe_payment_intent_id": None,
        "client_secret": None,
        "notes": inv.get("note", ""),
        "is_au_pair": False,
        "lessons_count": 1,
        "distance_miles": None,
        "remote": bool(t.get("allows_remote")),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    # Stripe PaymentIntent (best-effort)
    try:
        intent = await run_in_threadpool(
            lambda: stripe.PaymentIntent.create(
                amount=inv["price_cents"], currency=booking["currency"],
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
    }


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
    """Create booking-reminder (2h before) and review-request (after session) notifications on demand."""
    now = datetime.now(timezone.utc)
    # Reminders + review requests for parent's bookings
    if u["role"] == "parent":
        bookings = await db.bookings.find({"parent_id": u["id"], "payment_status": "paid"}, {"_id": 0}).to_list(200)
        for b in bookings:
            try:
                dt = datetime.fromisoformat(f"{b['date']}T{b['time']}:00+00:00")
            except Exception:
                continue
            delta_min = (dt - now).total_seconds() / 60
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
    else:
        await db.parents.delete_many({"user_id": uid})
    await db.bookings.delete_many({"$or": [{"parent_id": uid}, {"tutor_id": uid}]})
    await db.messages.delete_many({"$or": [{"from_user_id": uid}, {"to_user_id": uid}]})
    await db.reviews.delete_many({"parent_id": uid})
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
    # Seed the admin account if missing.
    admin_email = "copperstone17@gmail.com"
    admin = await db.users.find_one({"email": admin_email})
    if not admin:
        await db.users.insert_one({
            "id": str(uuid.uuid4()), "email": admin_email,
            "password_hash": hash_password("REDACTED-PASSWORD"),
            "name": "Babybabel Admin", "role": "admin", "avatar_url": None,
            "is_admin": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    elif not admin.get("is_admin"):
        await db.users.update_one({"email": admin_email}, {"$set": {"is_admin": True, "role": "admin"}})
    # Remove ALL tutor accounts that are not in the keep list.
    legacy_users = await db.users.find(
        {"role": "tutor", "email": {"$nin": list(KEEP_EMAILS)}},
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
    try:
        if EMERGENT_KEY:
            await run_in_threadpool(_init_storage_sync)
            logger.info("Object storage initialized")
    except Exception as e:
        logger.warning(f"Storage init deferred: {e}")
    await seed_data()


@api.get("/")
async def root():
    return {"app": "Babybabel", "status": "ok"}


app.include_router(api)


@app.on_event("shutdown")
async def shutdown():
    client.close()
