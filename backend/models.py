"""Pydantic request/response models shared by the route modules."""
import uuid
from typing import List, Literal, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator

from core import DATE_PATTERN, MAX_PRICE_CENTS, TIME_PATTERN

Role = Literal["parent", "tutor", "admin"]


# ---- Auth ----
class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    name: str = Field(min_length=1, max_length=80)
    role: Role
    timezone: Optional[str] = Field(default=None, max_length=64)
    # The person ticked "I agree to the Terms of Service and Privacy Policy". Recorded with the
    # date and the terms version, as proof of consent.
    accept_terms: bool = False

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("Please enter your name")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(max_length=200)
    code: Optional[str] = Field(default=None, max_length=12)  # admin sign-in only


class UserPublic(BaseModel):
    id: str
    email: EmailStr
    name: str
    role: Role
    avatar_url: Optional[str] = None
    is_admin: bool = False
    email_verified: bool = True
    timezone: Optional[str] = None


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserPublic


class UserUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=80)
    avatar_url: Optional[str] = None
    timezone: Optional[str] = Field(default=None, max_length=64)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6)
    new_password: str = Field(min_length=8, max_length=72)


class VerifyEmailRequest(BaseModel):
    code: str = Field(min_length=6, max_length=6)


class PushTokenIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    platform: Optional[str] = Field(default="", max_length=20)


# ---- Tutors ----
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
    verified: bool = False
    timezone: Optional[str] = None
    # Keys mon..sun → sorted "HH:MM" slot starts. Empty = no restrictions (legacy tutors).
    weekly_availability: dict = Field(default_factory=dict)
    # Populated only by list_tutors when the caller is a parent with saved coordinates.
    distance_miles: Optional[float] = None


class TutorProfileUpdate(BaseModel):
    bio: Optional[str] = Field(default=None, max_length=4000)
    languages: Optional[List[str]] = Field(default=None, max_length=20)
    hourly_rate_cents: Optional[int] = Field(default=None, ge=0, le=MAX_PRICE_CENTS)
    locations: Optional[List[str]] = Field(default=None, max_length=10)  # plain names, we geocode
    experience_years: Optional[int] = Field(default=None, ge=0, le=80)
    avatar_url: Optional[str] = None
    hero_image_url: Optional[str] = None
    accreditation_photo_url: Optional[str] = None
    accreditation_document_url: Optional[str] = None
    allows_remote: Optional[bool] = None
    weekly_availability: Optional[dict] = None
    timezone: Optional[str] = Field(default=None, max_length=64)


class VerificationSubmit(BaseModel):
    id_document_url: str = Field(min_length=1, max_length=300)
    background_check_url: str = Field(min_length=1, max_length=300)
    consent: bool


class VerificationDecision(BaseModel):
    note: Optional[str] = Field(default="", max_length=600)


# ---- Bookings ----
class BookingCreate(BaseModel):
    tutor_id: str
    date: str = Field(pattern=DATE_PATTERN)
    time: str = Field(pattern=TIME_PATTERN)
    duration_minutes: int = Field(gt=0, le=480)
    language: str = Field(min_length=1, max_length=60)
    notes: Optional[str] = Field(default="", max_length=2000)
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
    payment_status: str  # pending | paid | failed | canceled
    stripe_payment_intent_id: Optional[str] = None
    client_secret: Optional[str] = None
    notes: Optional[str] = ""
    is_au_pair: bool = False
    lessons_count: int = 1
    distance_miles: Optional[float] = None
    remote: bool = False
    housing_offered: Optional[str] = ""
    created_at: str
    timezone: Optional[str] = None
    # Direct bookings are requests the tutor accepts or declines. Legacy rows = accepted.
    tutor_response: str = "accepted"  # pending | accepted | declined
    respond_by: Optional[str] = None
    paid_at: Optional[str] = None
    canceled_at: Optional[str] = None
    canceled_by: Optional[str] = None  # parent | tutor | system | admin
    cancel_reason: Optional[str] = None
    refund_status: Optional[str] = None  # none | refunded | not_refunded | failed
    refund_cents: int = 0
    reschedule_count: int = 0


class CancelRequest(BaseModel):
    reason: Optional[str] = Field(default="", max_length=500)


class RescheduleRequest(BaseModel):
    date: str = Field(pattern=DATE_PATTERN)
    time: str = Field(pattern=TIME_PATTERN)


class RespondRequest(BaseModel):
    accept: bool
    note: Optional[str] = Field(default="", max_length=500)


# ---- Messages ----
class MessageCreate(BaseModel):
    to_user_id: str
    text: str = Field(min_length=1, max_length=4000)


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
    price_cents: int = Field(ge=100, le=MAX_PRICE_CENTS)
    date: str = Field(pattern=DATE_PATTERN)
    time: str = Field(pattern=TIME_PATTERN)
    duration_minutes: int = Field(gt=0, le=480)
    language: str = Field(min_length=1, max_length=60)
    note: Optional[str] = Field(default="", max_length=2000)


class Message(BaseModel):
    id: str
    from_user_id: str
    to_user_id: str
    text: str
    kind: str = "text"
    invitation: Optional[Invitation] = None
    created_at: str


# ---- Parents ----
class Child(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = Field(max_length=80)
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
    name: Optional[str] = Field(default=None, min_length=1, max_length=80)
    avatar_url: Optional[str] = None
    city: Optional[str] = Field(default=None, max_length=120)
    languages_desired: Optional[List[str]] = Field(default=None, max_length=20)
    hours_per_week: Optional[int] = Field(default=None, ge=0, le=80)
    learning_materials: Optional[str] = Field(default=None, max_length=4000)
    children: Optional[List[Child]] = Field(default=None, max_length=10)


# ---- Reviews ----
class ReviewCreate(BaseModel):
    tutor_id: str
    booking_id: str  # reviews must be tied to a paid booking with this tutor
    rating: int = Field(ge=1, le=5)
    comment: str = Field(default="", max_length=2000)


class Review(BaseModel):
    id: str
    tutor_id: str
    booking_id: Optional[str] = None
    parent_id: Optional[str] = None  # never included in the public list
    parent_name: str
    rating: int
    comment: str
    created_at: str


# ---- Misc ----
class EventIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    props: Optional[dict] = None


class NotificationOut(BaseModel):
    id: str
    kind: str
    title: str
    body: str
    at: str
    read: bool = False
