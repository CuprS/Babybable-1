"""Tutor search, profiles, availability and identity verification."""
import re
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from starlette.concurrency import run_in_threadpool

from core import (
    ACTIVE_STATUSES, WEEKDAYS, _normalize_slot, blocked_between, blocked_user_ids, current_user, db, is_tutor_verified,
    geocode, haversine_miles, notify_admins, now_iso, optional_user, push_notification, require_admin,
    slot_minutes, valid_timezone,
)
from models import TutorLocation, TutorProfile, TutorProfileUpdate, VerificationDecision, VerificationSubmit

router = APIRouter()


def tutor_doc_to_model(t: dict) -> TutorProfile:
    is_new = not (t.get("bio") and t.get("languages") and t.get("avatar_url"))
    locs = t.get("locations")
    if not locs and t.get("location"):  # backfill from legacy single 'location'
        locs = [{"name": t["location"], "latitude": t.get("latitude"), "longitude": t.get("longitude")}]
    locs = locs or []
    primary = locs[0] if locs else {}
    skip = ("is_new", "locations", "location", "latitude", "longitude", "verified")
    data = {k: t.get(k) for k in TutorProfile.model_fields.keys() if k not in skip}
    defaults = {
        "allows_remote": False, "weekly_availability": {}, "bio": "", "currency": "usd",
        "languages": [], "accreditation_urls": [], "hourly_rate_cents": 0, "experience_years": 0,
        "reviews_count": 0, "rating": 0.0,
    }
    for k, v in defaults.items():
        if data.get(k) is None:
            data[k] = v
    return TutorProfile(
        **data,
        is_new=is_new,
        verified=t.get("verification_status") == "verified",
        locations=[TutorLocation(**loc) for loc in locs],
        location=primary.get("name", "") or t.get("location", ""),
        latitude=primary.get("latitude") if primary else t.get("latitude"),
        longitude=primary.get("longitude") if primary else t.get("longitude"),
    )


@router.get("/tutors", response_model=List[TutorProfile])
async def list_tutors(
    q: Optional[str] = None,
    language: Optional[str] = None,
    min_rate: Optional[int] = None,
    max_rate: Optional[int] = None,
    max_miles: Optional[float] = None,
    include_remote: bool = True,
    verified_only: bool = False,
    u: Optional[dict] = Depends(optional_user),
):
    # Only verified tutors are listed: identity + background check approval is required
    # before anyone can book them. (verified_only is kept for older app versions.)
    query: dict = {"suspended": {"$ne": True}, "verification_status": "verified"}
    if language:
        query["languages"] = {"$regex": f"^{re.escape(language.strip()[:60])}$", "$options": "i"}
    if min_rate is not None:
        query.setdefault("hourly_rate_cents", {})["$gte"] = min_rate
    if max_rate is not None:
        query.setdefault("hourly_rate_cents", {})["$lte"] = max_rate
    if q:
        # Escape user input so a crafted regex can't pin DB CPU (ReDoS) or match unexpected fields.
        needle = re.escape(q.strip())[:80]
        query["$or"] = [{f: {"$regex": needle, "$options": "i"}} for f in ("name", "bio", "location", "languages")]
    if u:
        hidden = await blocked_user_ids(u["id"])
        if hidden:
            query["user_id"] = {"$nin": list(hidden)}
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
        points = [(loc["latitude"], loc["longitude"]) for loc in (doc.get("locations") or []) if loc.get("latitude") is not None]
        if not points and doc.get("latitude") is not None:
            points = [(doc["latitude"], doc["longitude"])]
        if not points:
            return None
        return round(min(haversine_miles(parent_coords[0], parent_coords[1], a, b) for a, b in points), 1)

    out: List[TutorProfile] = []
    for d in docs:
        model = tutor_doc_to_model(d)
        model.distance_miles = closest_distance(d)
        if max_miles is not None and parent_coords is not None:
            too_far = model.distance_miles is None or model.distance_miles > max_miles
            if too_far and not (include_remote and model.allows_remote):
                continue
        out.append(model)
    if parent_coords is not None:
        out.sort(key=lambda t: (t.distance_miles is None, t.distance_miles or 0))
    return out


@router.get("/tutors/map")
async def tutors_map(u: Optional[dict] = Depends(optional_user)):
    hidden = await blocked_user_ids(u["id"]) if u else set()
    docs = await db.tutors.find(
        {"suspended": {"$ne": True}, "verification_status": "verified", **({"user_id": {"$nin": list(hidden)}} if hidden else {})},
        {"_id": 0, "id": 1, "name": 1, "avatar_url": 1, "latitude": 1, "longitude": 1, "location": 1,
         "locations": 1, "hourly_rate_cents": 1, "allows_remote": 1, "verification_status": 1},
    ).to_list(200)
    out = []
    for d in docs:
        locs = d.get("locations") or ([{"name": d.get("location"), "latitude": d.get("latitude"), "longitude": d.get("longitude")}] if d.get("latitude") is not None else [])
        for loc in locs:
            if loc.get("latitude") is None or loc.get("longitude") is None:
                continue
            out.append({
                "id": d["id"], "name": d["name"], "avatar_url": d.get("avatar_url"),
                "latitude": loc["latitude"], "longitude": loc["longitude"], "location": loc.get("name"),
                "hourly_rate_cents": d.get("hourly_rate_cents"), "allows_remote": d.get("allows_remote", False),
                "verified": d.get("verification_status") == "verified",
            })
    return out


@router.get("/tutors/me/profile", response_model=TutorProfile)
async def get_my_tutor_profile(u: dict = Depends(current_user)):
    if u["role"] != "tutor":
        raise HTTPException(403, "Only tutors")
    d = await db.tutors.find_one({"user_id": u["id"]}, {"_id": 0})
    if not d:
        raise HTTPException(404, "Profile not found")
    return tutor_doc_to_model(d)


@router.patch("/tutors/me/profile", response_model=TutorProfile)
async def update_my_tutor_profile(patch: TutorProfileUpdate, u: dict = Depends(current_user)):
    if u["role"] != "tutor":
        raise HTTPException(403, "Only tutors")
    prev = await db.tutors.find_one({"user_id": u["id"]}, {"_id": 0})
    update = patch.model_dump(exclude_none=True)
    if "timezone" in update and not valid_timezone(update["timezone"]):
        raise HTTPException(422, "Unknown time zone")
    # Multi-location: geocode each and store as list of {name, lat, lng}.
    if "locations" in update:
        raw = [s.strip() for s in update["locations"] if s and s.strip()]
        prev_locs = {(loc.get("name") or "").strip().lower(): loc for loc in (prev or {}).get("locations", [])}
        geocoded = []
        for name in raw:
            existing = prev_locs.get(name.lower())
            if existing and existing.get("latitude") is not None:
                geocoded.append({"name": name, "latitude": existing["latitude"], "longitude": existing["longitude"]})
            else:
                coords = await run_in_threadpool(geocode, name) or {}
                geocoded.append({"name": name, "latitude": coords.get("latitude"), "longitude": coords.get("longitude")})
        update["locations"] = geocoded
        if geocoded:  # keep the legacy primary fields in sync for the map/list card
            update.update({"location": geocoded[0]["name"], "latitude": geocoded[0]["latitude"], "longitude": geocoded[0]["longitude"]})
    # Normalize weekly_availability: whitelist keys + normalize slots.
    if "weekly_availability" in update:
        wa_raw = update["weekly_availability"] or {}
        wa: dict = {}
        for day in WEEKDAYS:
            slots = wa_raw.get(day) if isinstance(wa_raw, dict) else None
            if isinstance(slots, list):
                clean = sorted({_normalize_slot(s) for s in slots if isinstance(s, str) and _normalize_slot(s)})
                if clean:
                    wa[day] = clean
        update["weekly_availability"] = wa
    if update:
        await db.tutors.update_one({"user_id": u["id"]}, {"$set": update})
        if "avatar_url" in update:
            await db.users.update_one({"id": u["id"]}, {"$set": {"avatar_url": update["avatar_url"]}})
    d = await db.tutors.find_one({"user_id": u["id"]}, {"_id": 0})
    return tutor_doc_to_model(d)


@router.get("/tutors/by-user/{user_id}", response_model=TutorProfile)
async def tutor_by_user(user_id: str, u: Optional[dict] = Depends(optional_user)):
    d = await db.tutors.find_one({"user_id": user_id}, {"_id": 0})
    if not d or d.get("suspended") or (u and await blocked_between(u["id"], user_id)):
        raise HTTPException(404, "Tutor profile not found")
    return tutor_doc_to_model(d)


@router.get("/tutors/{tutor_id}", response_model=TutorProfile)
async def get_tutor(tutor_id: str, u: Optional[dict] = Depends(optional_user)):
    d = await db.tutors.find_one({"id": tutor_id}, {"_id": 0})
    if not d or d.get("suspended") or (u and await blocked_between(u["id"], d["user_id"])):
        raise HTTPException(404, "Tutor not found")
    # Until verified, a profile is visible only to the tutor themself and to admins.
    is_owner_or_admin = bool(u) and (u["id"] == d["user_id"] or u.get("is_admin"))
    if not is_tutor_verified(d) and not is_owner_or_admin:
        raise HTTPException(404, "Tutor not found")
    return tutor_doc_to_model(d)


@router.get("/tutors/{tutor_id}/booked-slots")
async def tutor_booked_slots(tutor_id: str, start: Optional[str] = None, end: Optional[str] = None):
    """Every hourly slot start the tutor's active bookings cover, as [{date, time}].
    A 2-hour booking at 09:00 blocks 09:00 and 10:00."""
    q: dict = {"tutor_id": tutor_id, "payment_status": {"$in": list(ACTIVE_STATUSES)}, "is_au_pair": {"$ne": True}}
    if start:
        q["date"] = {"$gte": start}
    if end:
        q.setdefault("date", {})["$lte"] = end
    rows = await db.bookings.find(q, {"_id": 0, "date": 1, "time": 1, "duration_minutes": 1}).to_list(1000)
    out = []
    for r in rows:
        s = slot_minutes(r["time"])
        e = s + int(r.get("duration_minutes") or 60)
        hour = (s // 60) * 60
        while hour < e and hour < 24 * 60:
            out.append({"date": r["date"], "time": f"{hour // 60:02d}:00"})
            hour += 60
    return out


# ---- Identity verification ----
async def _own_upload(path: str, user_id: str) -> bool:
    return bool(await db.uploads.find_one({"path": path, "owner_id": user_id}, {"_id": 1}))


@router.get("/tutors/me/verification")
async def my_verification(u: dict = Depends(current_user)):
    if u["role"] != "tutor":
        raise HTTPException(403, "Only tutors")
    t = await db.tutors.find_one({"user_id": u["id"]}, {"_id": 0}) or {}
    return {
        "status": t.get("verification_status") or "none",
        "note": t.get("verification_note") or "",
        "submitted_at": t.get("verification_submitted_at"),
        "verified_at": t.get("verified_at"),
        "has_id_document": bool(t.get("id_document_url")),
        "has_background_check": bool(t.get("background_check_url")),
    }


@router.post("/tutors/me/verification")
async def submit_verification(body: VerificationSubmit, u: dict = Depends(current_user)):
    if u["role"] != "tutor":
        raise HTTPException(403, "Only tutors")
    if not body.consent:
        raise HTTPException(422, "Please confirm you agree to the identity and background check.")
    for path in (body.id_document_url, body.background_check_url):
        if not await _own_upload(path, u["id"]):
            raise HTTPException(422, "Documents must be uploaded from your device")
    await db.tutors.update_one({"user_id": u["id"]}, {"$set": {
        "id_document_url": body.id_document_url, "background_check_url": body.background_check_url,
        "verification_status": "pending", "verification_note": "", "verification_submitted_at": now_iso(),
    }})
    await notify_admins("verification", "Tutor verification to review", f"{u['name']} sent identity documents.")
    return await my_verification(u)


@router.get("/admin/verifications")
async def admin_list_verifications(status: str = "pending", _: dict = Depends(require_admin)):
    q = {"verification_status": status} if status in ("pending", "verified", "rejected") else {"verification_status": {"$in": ["pending", "verified", "rejected"]}}
    docs = await db.tutors.find(q, {"_id": 0, "id": 1, "user_id": 1, "name": 1, "avatar_url": 1, "verification_status": 1,
                                    "verification_note": 1, "verification_submitted_at": 1, "verified_at": 1,
                                    "id_document_url": 1, "background_check_url": 1,
                                    "accreditation_document_url": 1}).sort("verification_submitted_at", 1).to_list(200)
    emails = {x["id"]: x["email"] for x in await db.users.find({"id": {"$in": [d["user_id"] for d in docs]}}, {"_id": 0, "id": 1, "email": 1}).to_list(200)}
    for d in docs:
        d["email"] = emails.get(d["user_id"], "")
    return docs


async def _decide(tutor_id: str, status: str, note: str) -> dict:
    t = await db.tutors.find_one({"id": tutor_id}, {"_id": 0, "user_id": 1, "verification_status": 1})
    if not t or t.get("verification_status") in (None, "none"):
        raise HTTPException(404, "No verification request for that tutor")
    update = {"verification_status": status, "verification_note": note, "verification_decided_at": now_iso()}
    if status == "verified":
        update["verified_at"] = now_iso()
    await db.tutors.update_one({"id": tutor_id}, {"$set": update})
    if status == "verified":
        await push_notification(t["user_id"], "verification", "You're verified!", "Families now see a Verified badge on your profile.")
    else:
        await push_notification(t["user_id"], "verification", "Verification needs another look", note[:140] or "Please check your documents and resubmit.")
    return {"ok": True, "status": status}


@router.post("/admin/verifications/{tutor_id}/approve")
async def admin_approve_verification(tutor_id: str, body: Optional[VerificationDecision] = None, _: dict = Depends(require_admin)):
    return await _decide(tutor_id, "verified", (body.note if body else "") or "")


@router.post("/admin/verifications/{tutor_id}/reject")
async def admin_reject_verification(tutor_id: str, body: VerificationDecision, _: dict = Depends(require_admin)):
    note = (body.note or "").strip()
    if not note:
        raise HTTPException(422, "Tell the tutor what to fix")
    return await _decide(tutor_id, "rejected", note)
