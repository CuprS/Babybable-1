"""Accounts: signup/login, email verification, password reset, push tokens, account deletion."""
import os
import secrets
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from starlette.concurrency import run_in_threadpool

import storage
from booking_service import cancel_booking
from core import (
    SUSPENDED_MSG, W9_RETENTION_DAYS, booking_start_utc, check_own_files, clear_session_cookie, set_session_cookie,
    wants_cookie_session, current_user,
    current_user_even_if_paused, db, email_fingerprint, email_is_verified, hash_password, hash_secret,
    logger, make_token, new_code, now_iso, now_utc, rate_limit, session_minutes, tutor_profile_id,
    valid_timezone, verify_password,
)
from email_service import send_email
from models import (
    AuthResponse, ForgotPasswordRequest, LoginRequest, PushTokenIn, ResetPasswordRequest,
    SignupRequest, UserPublic, UserUpdate, VerifyEmailRequest,
)

router = APIRouter()

CODE_TTL_MINUTES = 15
# Bump when the Terms of Service or Privacy Policy change in a way people must agree to again.
TERMS_VERSION = "2026-11"
CODE_MAX_ATTEMPTS = 5


def user_to_public(u: dict) -> UserPublic:
    return UserPublic(
        id=u["id"], email=u["email"], name=u["name"], role=u["role"], avatar_url=u.get("avatar_url"),
        is_admin=bool(u.get("is_admin")), email_verified=email_is_verified(u), timezone=u.get("timezone"),
    )


def issue_session(request: Request, response: Response, user: dict) -> AuthResponse:
    """Phone apps get the token in the body (kept in encrypted device storage). The website asks
    for a cookie session: an HttpOnly cookie scripts can't read, and no token in the body."""
    minutes = session_minutes(user)
    token = make_token(user["id"], user["role"], int(user.get("token_version", 0)), minutes, bool(user.get("is_admin")))
    if wants_cookie_session(request):
        set_session_cookie(response, token, minutes)
        token = ""
    return AuthResponse(access_token=token, user=user_to_public(user))


@router.post("/auth/logout")
async def logout(response: Response):
    """Ends the website session on this browser (phone apps just forget their token)."""
    clear_session_cookie(response)
    return {"ok": True}


@router.post("/auth/logout-all")
async def logout_everywhere(response: Response, u: dict = Depends(current_user_even_if_paused)):
    """Signs out every device and browser: all existing sign-ins stop working at once."""
    await db.users.update_one({"id": u["id"]}, {"$inc": {"token_version": 1}})
    await db.push_tokens.delete_many({"user_id": u["id"]})
    clear_session_cookie(response)
    return {"ok": True}


# ---- One-time codes (email verification + password reset) ----
async def _issue_code(user: dict, purpose: str) -> str:
    code = new_code()
    await db.auth_codes.update_one(
        {"user_id": user["id"], "purpose": purpose},
        {"$set": {
            "user_id": user["id"], "purpose": purpose, "code_hash": hash_secret(code), "attempts": 0,
            "expires_at": (now_utc() + timedelta(minutes=CODE_TTL_MINUTES)).isoformat(), "created_at": now_iso(),
        }},
        upsert=True,
    )
    return code


async def _check_code(user: dict, purpose: str, code: str) -> bool:
    doc = await db.auth_codes.find_one({"user_id": user["id"], "purpose": purpose}, {"_id": 0})
    if not doc or doc.get("attempts", 0) >= CODE_MAX_ATTEMPTS:
        return False
    if datetime.fromisoformat(doc["expires_at"]) < now_utc():
        return False
    if not secrets.compare_digest(doc["code_hash"], hash_secret(code.strip())):
        await db.auth_codes.update_one({"user_id": user["id"], "purpose": purpose}, {"$inc": {"attempts": 1}})
        return False
    await db.auth_codes.delete_one({"user_id": user["id"], "purpose": purpose})
    return True


async def _email_code(to: str, purpose: str, code: str) -> None:
    if os.environ.get("DEV_LOG_EMAIL_CODES", "").lower() == "true":
        logger.info(f"[dev] {purpose} code for {to}: {code}")  # local development only
    if purpose == "verify":
        subject, lead = "Your Babybabel verification code", "Use this code in the app to confirm your email address."
    elif purpose == "admin_login":
        subject = "Your Babybabel admin sign-in code"
        lead = ("Someone (hopefully you) entered the admin password. Use this code to finish signing in. "
                "If it wasn't you, change the admin password now.")
    else:
        subject, lead = "Your Babybabel reset code", "Use this code in the app to choose a new password. If you didn't ask for this, you can ignore this email."
    html = (
        '<table role="presentation" width="100%" style="background:#FAF8F5"><tr><td style="padding:24px;font-family:Arial,sans-serif;color:#2C2421">'
        f'<h2 style="margin:0 0 12px;color:#B83A23">{subject}</h2>'
        f'<p style="font-size:16px">{lead}</p>'
        f'<p style="font-size:32px;font-weight:bold;letter-spacing:6px;margin:16px 0">{code}</p>'
        f'<p style="font-size:14px;color:#6b6260">The code expires in {CODE_TTL_MINUTES} minutes.</p>'
        '</td></tr></table>'
    )
    try:
        await send_email(to=to, subject=subject, html=html)
    except ValueError as e:
        logger.error(f"code email rejected by guardrail: {e}")


# ---- Signup / login ----
ADMIN_CODE_SENT_MSG = "We've emailed a 6-digit sign-in code to the admin address. Enter it to finish signing in."


@router.post("/auth/signup", response_model=AuthResponse, status_code=201)
async def signup(body: SignupRequest, request: Request, response: Response):
    rate_limit("signup", max_hits=5, per_seconds=600, request=request)
    email = body.email.lower().strip()
    if body.role not in ("parent", "tutor"):
        # Admin roles are provisioned server-side only; never accept via signup.
        raise HTTPException(400, "Invalid role")
    if not body.accept_terms:
        raise HTTPException(400, "Please agree to the Terms of Service and Privacy Policy to create an account.")
    if body.password.strip().lower() in (email, email.split("@")[0], body.name.lower()):
        raise HTTPException(400, "Please choose a password that isn't your name or email address.")
    if await db.users.find_one({"email": email}):
        # Generic error prevents easy email enumeration via signup.
        raise HTTPException(400, "We couldn't create that account. Try logging in or use a different email.")
    uid = str(uuid.uuid4())
    fp = email_fingerprint(email)
    # Block-evasion guard: a deleted account that was paused stays paused if re-created.
    tomb = await db.account_tombstones.find_one({"email_fp": fp}, {"_id": 0})
    if not (tomb and tomb.get("suspended")):
        # A live paused account with the same email (e.g. x+alt@ while x@ is paused) also counts.
        related = await db.blocks.distinct("blocked_id", {"blocked_email_fp": fp})
        if related and await db.users.find_one({"id": {"$in": related}, "suspended": True}, {"_id": 1}):
            tomb = {"suspended": True}
    doc = {
        "id": uid, "email": email, "password_hash": hash_password(body.password),
        "name": body.name, "role": body.role, "avatar_url": None,
        "email_verified": False,
        "timezone": body.timezone if valid_timezone(body.timezone) else None,
        "created_at": now_iso(),
    }
    doc["terms_accepted_at"], doc["terms_version"] = doc["created_at"], TERMS_VERSION
    if tomb and tomb.get("suspended"):
        doc.update({"suspended": True, "suspended_at": doc["created_at"],
                    "suspended_reason": "Re-created an account that was paused for review"})
    await db.users.insert_one(doc)
    # Block-evasion guard: every block placed on an account with this email (deleted or a
    # +alias / Gmail-dot variant) is copied onto the new account. Originals stay untouched.
    for b in await db.blocks.find({"blocked_email_fp": fp}, {"_id": 0}).to_list(1000):
        await db.blocks.update_one(
            {"blocker_id": b["blocker_id"], "blocked_id": uid},
            {"$setOnInsert": {**b, "id": str(uuid.uuid4()), "blocked_id": uid, "blocked_deleted": False, "carried_over": True}},
            upsert=True,
        )
    if body.role == "tutor":
        await db.tutors.insert_one({
            "id": str(uuid.uuid4()), "user_id": uid, "name": body.name, "avatar_url": None,
            "bio": "", "languages": [], "hourly_rate_cents": 3000, "currency": "usd",
            "location": "", "experience_years": 0, "rating": 0.0, "reviews_count": 0,
            "accreditation_urls": [], "hero_image_url": None, "weekly_availability": {},
            "timezone": doc["timezone"], "verification_status": "none",
            "created_at": now_iso(),
            **({"suspended": True} if doc.get("suspended") else {}),
        })
    if doc.get("suspended"):
        raise HTTPException(423, SUSPENDED_MSG)
    await _email_code(email, "verify", await _issue_code(doc, "verify"))
    return issue_session(request, response, doc)


@router.post("/auth/login", response_model=AuthResponse)
async def login(body: LoginRequest, request: Request, response: Response):
    email = body.email.lower().strip()
    rate_limit("login", max_hits=8, per_seconds=300, request=request)
    # Counted across all addresses too, so password guessing can't be spread over many IPs.
    rate_limit("login-any-ip", max_hits=20, per_seconds=900, request=request, key=email, per_ip=False)
    u = await db.users.find_one({"email": email})
    if not u or not verify_password(body.password, u["password_hash"]):
        raise HTTPException(401, "Invalid email or password")
    if u.get("is_admin"):
        # Second step for the admin: a 6-digit code emailed to the admin address.
        if not body.code:
            await _email_code(u["email"], "admin_login", await _issue_code(u, "admin_login"))
            raise HTTPException(428, ADMIN_CODE_SENT_MSG)
        if not await _check_code(u, "admin_login", body.code):
            raise HTTPException(400, "That code is invalid or has expired. Log in again to get a new one.")
        logger.info("admin signed in")
    elif u.get("suspended"):
        raise HTTPException(423, SUSPENDED_MSG)
    return issue_session(request, response, u)


@router.get("/auth/me", response_model=UserPublic)
async def me(u: dict = Depends(current_user)):
    return user_to_public(u)


@router.patch("/auth/me", response_model=UserPublic)
async def update_me(patch: UserUpdate, u: dict = Depends(current_user)):
    update = patch.model_dump(exclude_none=True)
    if "timezone" in update and not valid_timezone(update["timezone"]):
        raise HTTPException(422, "Unknown time zone")
    if "avatar_url" in update:
        await check_own_files(u["id"], [update["avatar_url"]], [u.get("avatar_url")])
    if update:
        await db.users.update_one({"id": u["id"]}, {"$set": update})
        profile_update = {k: v for k, v in update.items() if k in ("name", "avatar_url")}
        if profile_update and u["role"] == "tutor":
            await db.tutors.update_one({"user_id": u["id"]}, {"$set": profile_update})
        elif profile_update and u["role"] == "parent":
            await db.parents.update_one({"user_id": u["id"]}, {"$set": profile_update}, upsert=True)
        if "timezone" in update and u["role"] == "tutor":
            # A tutor's sessions happen in their zone — set it once, don't overwrite a deliberate choice.
            await db.tutors.update_one({"user_id": u["id"], "timezone": {"$in": [None, ""]}}, {"$set": {"timezone": update["timezone"]}})
    fresh = await db.users.find_one({"id": u["id"]}, {"_id": 0})
    return user_to_public(fresh)


# ---- Email verification ----
@router.post("/auth/verify-email", response_model=UserPublic)
async def verify_email(body: VerifyEmailRequest, request: Request, u: dict = Depends(current_user)):
    rate_limit("verify", max_hits=10, per_seconds=900, request=request, key=u["id"], per_ip=False)
    if email_is_verified(u):
        return user_to_public(u)
    if not await _check_code(u, "verify", body.code):
        raise HTTPException(400, "That code is invalid or has expired. Request a new one.")
    await db.users.update_one({"id": u["id"]}, {"$set": {"email_verified": True, "email_verified_at": now_iso()}})
    return user_to_public({**u, "email_verified": True})


@router.post("/auth/resend-verification")
async def resend_verification(request: Request, u: dict = Depends(current_user)):
    rate_limit("resend", max_hits=3, per_seconds=900, request=request, key=u["id"])
    if not email_is_verified(u):
        await _email_code(u["email"], "verify", await _issue_code(u, "verify"))
    return {"ok": True}


# ---- Password reset ----
@router.post("/auth/forgot-password")
async def forgot_password(body: ForgotPasswordRequest, request: Request):
    """Always answers the same way, so it can't be used to find out who has an account."""
    email = body.email.lower().strip()
    rate_limit("forgot", max_hits=5, per_seconds=3600, request=request, key=email)
    rate_limit("forgot-any-ip", max_hits=5, per_seconds=3600, request=request, key=email, per_ip=False)
    u = await db.users.find_one({"email": email}, {"_id": 0})
    # The admin password is changed on the server instead (admin_tools.py), so control of the
    # admin mailbox alone is never enough to take over the admin account.
    if u and not u.get("is_admin"):
        await _email_code(email, "reset", await _issue_code(u, "reset"))
    return {"ok": True, "message": "If that email has an account, we've sent a 6-digit code to it."}


@router.post("/auth/reset-password", response_model=AuthResponse)
async def reset_password(body: ResetPasswordRequest, request: Request, response: Response):
    email = body.email.lower().strip()
    rate_limit("reset", max_hits=10, per_seconds=900, request=request, key=email)
    rate_limit("reset-any-ip", max_hits=10, per_seconds=900, request=request, key=email, per_ip=False)
    u = await db.users.find_one({"email": email}, {"_id": 0})
    if not u or u.get("is_admin") or not await _check_code(u, "reset", body.code):
        raise HTTPException(400, "That code is invalid or has expired. Request a new one.")
    version = int(u.get("token_version", 0)) + 1  # signs out every existing session
    # Receiving the code proves they own the address, so the email counts as verified too.
    await db.users.update_one({"id": u["id"]}, {"$set": {
        "password_hash": hash_password(body.new_password), "password_changed_at": now_iso(),
        "token_version": version, "email_verified": True,
    }})
    await db.auth_codes.delete_many({"user_id": u["id"]})
    if u.get("suspended") and not u.get("is_admin"):
        raise HTTPException(423, SUSPENDED_MSG)
    fresh = {**u, "email_verified": True, "token_version": version}
    return issue_session(request, response, fresh)


# ---- Push tokens ----
@router.post("/push-tokens")
async def register_push_token(body: PushTokenIn, u: dict = Depends(current_user)):
    tok = body.token.strip()
    if not (tok.startswith("ExponentPushToken[") or tok.startswith("ExpoPushToken[")):
        raise HTTPException(422, "Not an Expo push token")
    await db.push_tokens.update_one(
        {"token": tok},
        {"$set": {"token": tok, "user_id": u["id"], "platform": body.platform or "", "updated_at": now_iso()}},
        upsert=True,
    )
    return {"ok": True}


@router.delete("/push-tokens")
async def remove_push_token(token: str, u: dict = Depends(current_user)):
    await db.push_tokens.delete_one({"token": token, "user_id": u["id"]})
    return {"ok": True}


# ---- Delete account ----
@router.delete("/auth/me")
async def delete_account(response: Response, u: dict = Depends(current_user_even_if_paused)):
    """Delete the person and their content, but keep anonymised booking and payment records:
    the other side's history, accounting and tax reporting depend on them."""
    uid = u["id"]
    is_tutor = u["role"] == "tutor"
    profile_id = await tutor_profile_id(uid) if is_tutor else None
    booking_q = {"tutor_id": profile_id} if profile_id else {"parent_id": uid}

    # 1) Upcoming sessions can't happen any more: cancel them (refunds follow the normal policy).
    now = now_utc()
    async for b in db.bookings.find({**booking_q, "payment_status": {"$in": ["pending", "paid"]}}, {"_id": 0}):
        start = booking_start_utc(b)
        if start is None or start > now:
            await cancel_booking(b, by_role="tutor" if is_tutor else "parent", reason="Account deleted")

    # 2) Past and cancelled bookings stay, without the deleted person's name.
    if is_tutor and profile_id:
        await db.bookings.update_many({"tutor_id": profile_id}, {"$set": {"tutor_name": "Former tutor", "tutor_deleted": True}})
        await db.reviews.delete_many({"tutor_id": profile_id})
        await db.favorites.delete_many({"tutor_id": profile_id})
        await db.tutors.delete_many({"user_id": uid})
        # IRS: payers keep W-9s for 4 years. Keep it (TIN stays encrypted), purge later.
        retain_until = (now + timedelta(days=W9_RETENTION_DAYS)).isoformat()
        await db.w9_forms.update_many({"tutor_user_id": uid}, {"$set": {"account_deleted_at": now.isoformat(), "retain_until": retain_until}})
    else:
        await db.bookings.update_many({"parent_id": uid}, {"$set": {"parent_name": "Deleted user", "parent_deleted": True}})
        await db.parents.delete_many({"user_id": uid})
        # Reviews keep counting toward the tutor's rating, but no longer carry the name.
        await db.reviews.update_many({"parent_id": uid}, {"$set": {"parent_name": "Former Babybabel parent"}})

    await db.messages.delete_many({"$or": [{"from_user_id": uid}, {"to_user_id": uid}]})
    await db.notifications.delete_many({"user_id": uid})
    await db.events.delete_many({"user_id": uid})
    await db.favorites.delete_many({"user_id": uid})
    await db.push_tokens.delete_many({"user_id": uid})
    await db.auth_codes.delete_many({"user_id": uid})
    await db.posts.delete_many({"author_id": uid})

    # 3) Uploaded files: remove from storage (best effort) and drop the records, which makes
    # them unreachable through /api/files even if storage keeps a copy.
    paths = [d["path"] for d in await db.uploads.find({"owner_id": uid}, {"_id": 0, "path": 1}).to_list(5000)]
    failed = 0
    for p in paths:
        if not await run_in_threadpool(storage.delete_object, p):
            failed += 1
    if failed:
        logger.warning(f"account {uid}: {failed}/{len(paths)} stored files could not be deleted from storage")
    await db.uploads.delete_many({"owner_id": uid})

    # Blocks this user placed go away; blocks placed ON them are kept (keyed by email
    # fingerprint) so deleting and re-signing up can't be used to evade a block.
    await db.blocks.delete_many({"blocker_id": uid})
    fp = email_fingerprint(u["email"])
    await db.blocks.update_many({"blocked_id": uid}, {"$set": {"blocked_email_fp": fp, "blocked_deleted": True}})
    if u.get("suspended") or await db.blocks.find_one({"blocked_email_fp": fp}, {"_id": 1}):
        await db.account_tombstones.update_one(
            {"email_fp": fp},
            # $max: a paused flag is never lowered by deleting a non-paused alias later.
            {"$set": {"email_fp": fp, "deleted_at": now_iso()}, "$max": {"suspended": bool(u.get("suspended"))}},
            upsert=True,
        )
    # Platform earnings intentionally preserved (accounting record); no PII lives on that doc.
    await db.users.delete_one({"id": uid})
    clear_session_cookie(response)
    return {"deleted": True}
