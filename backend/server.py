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

# ---- PostHog (backend) ----
_posthog_client = None
def _get_posthog():
    global _posthog_client
    if _posthog_client is not None:
        return _posthog_client
    key = os.environ.get("POSTHOG_PROJECT_TOKEN")
    if not key:
        _posthog_client = False
        return False
    try:
        from posthog import Posthog
        _posthog_client = Posthog(key, host=os.environ.get("POSTHOG_HOST", "https://us.i.posthog.com"))
    except Exception:
        _posthog_client = False
    return _posthog_client


def ph_capture(event: str, distinct_id: str, props: Optional[dict] = None):
    client = _get_posthog()
    if not client:
        return
    try:
        client.capture(event=event, distinct_id=str(distinct_id), properties=(props or {}) | {"source": "server"})
    except Exception:
        pass

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


# ---- Models ----
Role = Literal["parent", "tutor"]


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


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserPublic


class TutorProfile(BaseModel):
    id: str
    user_id: str
    name: str
    avatar_url: Optional[str] = None
    bio: str = ""
    languages: List[str] = []
    hourly_rate_cents: int = 3000
    currency: str = "usd"
    location: str = ""
    experience_years: int = 0
    rating: float = 0.0
    reviews_count: int = 0
    accreditation_urls: List[str] = []
    hero_image_url: Optional[str] = None
    is_new: bool = False  # true when profile hasn't been completed yet


class TutorProfileUpdate(BaseModel):
    bio: Optional[str] = None
    languages: Optional[List[str]] = None
    hourly_rate_cents: Optional[int] = None
    location: Optional[str] = None
    experience_years: Optional[int] = None
    avatar_url: Optional[str] = None
    hero_image_url: Optional[str] = None
    accreditation_urls: Optional[List[str]] = None


class BookingCreate(BaseModel):
    tutor_id: str
    date: str  # ISO date string
    time: str  # HH:MM
    duration_minutes: int = Field(gt=0, le=480)
    language: str
    notes: Optional[str] = ""


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
    created_at: str


class MessageCreate(BaseModel):
    to_user_id: str
    text: str


class Message(BaseModel):
    id: str
    from_user_id: str
    to_user_id: str
    text: str
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
    return UserPublic(id=u["id"], email=u["email"], name=u["name"], role=u["role"], avatar_url=u.get("avatar_url"))


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
    ph_capture("signup", uid, {"role": body.role, "method": "email"})
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
    if ext not in ("jpg", "jpeg", "png", "webp", "heic", "heif"):
        ext = "jpg"
    path = f"{APP_NAME}/uploads/{u['id']}/{uuid.uuid4()}.{ext}"
    data = await file.read()
    ctype = file.content_type or "image/jpeg"
    try:
        await run_in_threadpool(_put_object_sync, path, data, ctype)
    except Exception as e:
        logger.exception("upload failed")
        raise HTTPException(502, f"Upload failed: {e}")
    await db.uploads.insert_one({
        "path": path, "owner_id": u["id"], "content_type": ctype,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return {"path": path, "url": f"/api/files/{path}"}


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
    data = {k: t.get(k) for k in TutorProfile.model_fields.keys() if k != "is_new"}
    return TutorProfile(**data, is_new=is_new)


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
    update = {k: v for k, v in patch.model_dump(exclude_none=True).items()}
    if update:
        await db.tutors.update_one({"user_id": u["id"]}, {"$set": update})
        # Also sync avatar to users if present
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
    amount = (t["hourly_rate_cents"] * body.duration_minutes + 59) // 60
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
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.messages.insert_one(m)
    await push_notification(body.to_user_id, "chat", f"New message from {u['name']}", body.text[:120])
    return Message(**m)


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
    doc = await db.parents.find_one({"user_id": u["id"]}, {"_id": 0})
    fresh = await db.users.find_one({"id": u["id"]}, {"_id": 0})
    return parent_doc_to_model(doc, fresh["name"] if fresh else u["name"])


# ---- Favourites, events, notifications ----
class EventIn(BaseModel):
    name: str
    props: Optional[dict] = None


@api.post("/events")
async def track_event(body: EventIn, u: dict = Depends(current_user)):
    await db.events.insert_one({
        "user_id": u["id"], "role": u["role"], "name": body.name,
        "props": body.props or {}, "at": datetime.now(timezone.utc).isoformat(),
    })
    ph_capture(body.name, u["id"], (body.props or {}) | {"role": u["role"]})
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
        "experience_years": 8, "rating": 4.9, "reviews_count": 42,
        "avatar_url": "https://images.pexels.com/photos/38808650/pexels-photo-38808650.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=650&w=940",
        "hero_image_url": "https://images.unsplash.com/photo-1583468982228-19f19164aee2?crop=entropy&cs=srgb&fm=jpg&q=85&w=1200",
        "accreditation_urls": ["https://images.unsplash.com/photo-1589330694653-ded6df03f754?crop=entropy&cs=srgb&fm=jpg&q=85&w=800"],
    },
    {
        "name": "Marie Dubois", "email": "marie@babybabel.dev",
        "bio": "Certified French tutor and childcare specialist. I turn every session into a little Parisian adventure.",
        "languages": ["French", "English"], "hourly_rate_cents": 4200, "location": "Lyon, FR",
        "experience_years": 12, "rating": 4.8, "reviews_count": 67,
        "avatar_url": "https://images.unsplash.com/photo-1573497019940-1c28c88b4f3e?crop=entropy&cs=srgb&fm=jpg&q=85&w=800",
        "hero_image_url": "https://images.unsplash.com/photo-1503454537195-1dcabb73ffb9?crop=entropy&cs=srgb&fm=jpg&q=85&w=1200",
        "accreditation_urls": [],
    },
]

KEEP_EMAILS = {t["email"] for t in SEED_TUTORS}


async def seed_data():
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
