"""Startup tasks: indexes, sample data, one-off migrations."""
import os
import secrets
import uuid

from cryptography.fernet import InvalidToken
from pymongo.errors import DuplicateKeyError, OperationFailure

from core import (
    ADMIN_EMAIL, ACTIVE_STATUSES, _fernets, db, decrypt_tin, encrypt_tin, hash_password, logger, now_iso,
    slot_key,
)

SEED_TUTORS = [
    {
        "name": "Sofía García", "email": "sofia@babybabel.dev",
        "bio": "Bilingual educator with 8 years of experience helping children fall in love with Spanish through play, songs, and stories.",
        "languages": ["Spanish", "English"], "hourly_rate_cents": 3500, "location": "Barcelona, ES",
        "latitude": 41.3874, "longitude": 2.1686, "allows_remote": True, "timezone": "Europe/Madrid",
        "experience_years": 8, "rating": 4.9, "reviews_count": 42,
        "avatar_url": "https://images.pexels.com/photos/38808650/pexels-photo-38808650.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=650&w=940",
        "hero_image_url": "https://images.unsplash.com/photo-1583468982228-19f19164aee2?crop=entropy&cs=srgb&fm=jpg&q=85&w=1200",
        "accreditation_urls": ["https://images.unsplash.com/photo-1589330694653-ded6df03f754?crop=entropy&cs=srgb&fm=jpg&q=85&w=800"],
    },
    {
        "name": "Marie Dubois", "email": "marie@babybabel.dev",
        "bio": "Certified French tutor and childcare specialist. I turn every session into a little Parisian adventure.",
        "languages": ["French", "English"], "hourly_rate_cents": 4200, "location": "Lyon, FR",
        "latitude": 45.7640, "longitude": 4.8357, "allows_remote": False, "timezone": "Europe/Paris",
        "experience_years": 12, "rating": 4.8, "reviews_count": 67,
        "avatar_url": "https://images.unsplash.com/photo-1573497019940-1c28c88b4f3e?crop=entropy&cs=srgb&fm=jpg&q=85&w=800",
        "hero_image_url": "https://images.unsplash.com/photo-1503454537195-1dcabb73ffb9?crop=entropy&cs=srgb&fm=jpg&q=85&w=1200",
        "accreditation_urls": [],
    },
]
KEEP_EMAILS = {t["email"] for t in SEED_TUTORS}


async def ensure_indexes() -> None:
    specs = [
        (db.users, "email", {"unique": True}),
        (db.tutors, "user_id", {}),
        (db.tutors, "verification_status", {}),
        (db.bookings, "parent_id", {}),
        (db.bookings, "tutor_id", {}),
        (db.bookings, [("payment_status", 1), ("date", 1)], {}),
        # The database refuses two active bookings starting at the same tutor/date/time.
        (db.bookings, "slot_key", {"unique": True, "sparse": True}),
        (db.messages, [("from_user_id", 1), ("to_user_id", 1)], {}),
        (db.messages, [("from_user_id", 1), ("created_at", -1)], {}),
        (db.messages, [("from_user_id", 1), ("cold", 1), ("created_at", -1)], {}),
        (db.notifications, [("user_id", 1), ("kind", 1)], {}),
        (db.notifications, [("user_id", 1), ("at", -1)], {}),
        (db.blocks, [("blocker_id", 1), ("blocked_id", 1)], {"unique": True}),
        (db.blocks, "blocked_id", {}),
        (db.blocks, "blocked_email_fp", {"sparse": True}),
        (db.account_tombstones, "email_fp", {"unique": True}),
        (db.w9_forms, "tutor_user_id", {"unique": True}),
        (db.posts, "status", {}),
        (db.posts, "author_id", {}),
        (db.push_tokens, "token", {"unique": True}),
        (db.push_tokens, "user_id", {}),
        (db.auth_codes, [("user_id", 1), ("purpose", 1)], {"unique": True}),
        (db.reviews, "booking_id", {}),
    ]
    for coll, keys, opts in specs:
        try:
            await coll.create_index(keys, **opts)
        except (OperationFailure, DuplicateKeyError) as e:
            # Usually existing duplicate data; the app still works, just without that guarantee.
            logger.error(f"index {coll.name}.{keys} not created: {e}")


async def backfill_slot_keys() -> None:
    """Give existing active bookings a slot_key so the unique index protects them too."""
    q = {"slot_key": {"$exists": False}, "payment_status": {"$in": list(ACTIVE_STATUSES)}, "is_au_pair": {"$ne": True}}
    async for b in db.bookings.find(q, {"_id": 0, "id": 1, "tutor_id": 1, "date": 1, "time": 1}):
        try:
            await db.bookings.update_one({"id": b["id"]}, {"$set": {"slot_key": slot_key(b["tutor_id"], b["date"], b["time"])}})
        except DuplicateKeyError:
            logger.warning(f"booking {b['id']} double-books an existing slot; left without slot_key")


async def seed_data() -> None:
    admin_pw = os.environ.get("ADMIN_INITIAL_PASSWORD")
    if not ADMIN_EMAIL or not admin_pw:
        logger.warning("ADMIN_EMAIL / ADMIN_INITIAL_PASSWORD not set — admin seed skipped")
    admin = await db.users.find_one({"email": ADMIN_EMAIL}) if ADMIN_EMAIL else None
    if not admin and ADMIN_EMAIL and admin_pw:
        await db.users.insert_one({
            "id": str(uuid.uuid4()), "email": ADMIN_EMAIL, "password_hash": hash_password(admin_pw),
            "name": "Babybabel Admin", "role": "admin", "avatar_url": None, "is_admin": True,
            "email_verified": True, "created_at": now_iso(),
        })
    elif admin and not admin.get("is_admin"):
        await db.users.update_one({"email": ADMIN_EMAIL}, {"$set": {"is_admin": True, "role": "admin"}})
    # Sample tutors (fictional people with made-up ratings) exist only when explicitly asked for,
    # e.g. by the automated tests. Otherwise any demo account (@babybabel.dev) is removed — this
    # never touches real signups, which can't use that domain.
    want_samples = os.environ.get("SEED_SAMPLE_TUTORS", "").lower() == "true"
    keep = list(KEEP_EMAILS) if want_samples else []
    legacy = await db.users.find(
        {"role": "tutor", "email": {"$regex": "@babybabel\\.dev$", "$nin": keep}}, {"_id": 0, "id": 1},
    ).to_list(500)
    for lu in legacy:
        profile = await db.tutors.find_one({"user_id": lu["id"]}, {"_id": 0, "id": 1})
        if profile:
            await db.reviews.delete_many({"tutor_id": profile["id"]})
            await db.favorites.delete_many({"tutor_id": profile["id"]})
        await db.tutors.delete_many({"user_id": lu["id"]})
        await db.users.delete_one({"id": lu["id"]})
    if legacy:
        logger.info(f"Removed {len(legacy)} sample tutor account(s)")
    if not want_samples:
        return
    # Sample tutors used to share the public password "password123", so anyone could sign in
    # as them on a live site. Use SEED_TUTOR_PASSWORD, or an unguessable random one.
    seed_pw = os.environ.get("SEED_TUTOR_PASSWORD") or secrets.token_urlsafe(24)
    for t in SEED_TUTORS:
        if await db.users.find_one({"email": t["email"]}, {"_id": 1}):
            continue
        uid, tid = str(uuid.uuid4()), str(uuid.uuid4())
        await db.users.insert_one({
            "id": uid, "email": t["email"], "password_hash": hash_password(seed_pw), "name": t["name"],
            "role": "tutor", "avatar_url": t["avatar_url"], "email_verified": True, "timezone": t["timezone"],
            "created_at": now_iso(),
        })
        await db.tutors.insert_one({
            "id": tid, "user_id": uid, "name": t["name"], "avatar_url": t["avatar_url"],
            "bio": t["bio"], "languages": t["languages"], "hourly_rate_cents": t["hourly_rate_cents"],
            "currency": "usd", "location": t["location"], "experience_years": t["experience_years"],
            "latitude": t["latitude"], "longitude": t["longitude"], "allows_remote": t["allows_remote"],
            "timezone": t["timezone"], "rating": t["rating"], "reviews_count": t["reviews_count"],
            "accreditation_urls": t["accreditation_urls"], "hero_image_url": t["hero_image_url"],
            # Bookable straight away so tests and demos don't need an admin approval step.
            "verification_status": "verified", "verified_at": now_iso(), "created_at": now_iso(),
        })


async def migrate_w9_tins() -> None:
    """Re-encrypt W-9 TINs stored with the legacy base64 scheme or a retired Fernet key. Idempotent."""
    migrated = failed = 0
    async for doc in db.w9_forms.find({"tin_encrypted": {"$ne": None}}, {"_id": 0, "tutor_user_id": 1, "tin_encrypted": 1}):
        token = doc.get("tin_encrypted") or ""
        try:
            _fernets[0].decrypt(token.encode())
            continue  # already under the current primary key
        except InvalidToken:
            pass
        plain = decrypt_tin(token)
        if not plain:
            failed += 1
            continue
        await db.w9_forms.update_one({"tutor_user_id": doc["tutor_user_id"]}, {"$set": {"tin_encrypted": encrypt_tin(plain)}})
        migrated += 1
    if migrated or failed:
        logger.info(f"W-9 TIN migration: re-encrypted {migrated} record(s), {failed} failed.")
