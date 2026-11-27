"""W-9 tax forms (TIN encrypted at rest)."""
from datetime import datetime, timezone
from typing import List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from cryptography.fernet import InvalidToken

import core
from core import db, current_user, require_admin, encrypt_tin, tutor_has_completed_session

router = APIRouter()


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


@router.post("/w9", response_model=W9Form, status_code=201)
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


@router.get("/w9/me", response_model=Optional[W9Form])
async def my_w9(u: dict = Depends(current_user)):
    if u.get("role") != "tutor":
        raise HTTPException(403, "Only tutors have W-9 forms")
    doc = await db.w9_forms.find_one({"tutor_user_id": u["id"]}, {"_id": 0})
    return w9_public(doc) if doc else None


@router.get("/w9/me/status")
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


@router.get("/admin/w9", response_model=List[W9Form])
async def admin_list_w9(u: dict = Depends(require_admin), limit: int = 200):
    docs = await db.w9_forms.find({}, {"_id": 0}).sort("updated_at", -1).to_list(limit)
    return [w9_public(d) for d in docs]


@router.get("/admin/w9/{tutor_user_id}", response_model=W9Form)
async def admin_get_w9(tutor_user_id: str, u: dict = Depends(require_admin)):
    doc = await db.w9_forms.find_one({"tutor_user_id": tutor_user_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "W-9 not found for that tutor")
    return w9_public(doc)


@router.get("/admin/w9-encryption-status")
async def admin_w9_encryption_status(u: dict = Depends(require_admin)):
    """Ops endpoint: shows key config + counts of records under old vs primary key.
    Use during a rotation to know when it's safe to remove the retired key."""
    total = await db.w9_forms.count_documents({})
    primary = 0
    legacy = 0
    async for doc in db.w9_forms.find({}, {"_id": 0, "tin_encrypted": 1}):
        token = (doc or {}).get("tin_encrypted") or ""
        try:
            core._fernets[0].decrypt(token.encode())
            primary += 1
        except InvalidToken:
            legacy += 1
    return {
        "keys_configured": len(core._fernets),
        "ephemeral_key": core._EPHEMERAL_W9_KEY,
        "records_total": total,
        "records_on_primary_key": primary,
        "records_needing_rotation": legacy,
    }
