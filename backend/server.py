"""Babybabel API — app assembly.

Feature code lives in routes/ (HTTP endpoints), core.py (shared infrastructure),
models.py (request/response shapes), storage.py (uploaded files), email_service.py,
booking_service.py, workers.py and seed.py.
Run with: uvicorn server:app
"""
import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from starlette.concurrency import run_in_threadpool
from starlette.middleware.cors import CORSMiddleware

import core
import storage
from core import client, db, logger  # noqa: F401  (re-exported)
# Re-exported for tests and scripts that do `import server`.
from core import decrypt_tin, encrypt_tin, is_legacy_tin_token  # noqa: F401
from seed import backfill_slot_keys, ensure_indexes, migrate_w9_tins, seed_data
from workers import maintenance_loop

_migrate_w9_tins = migrate_w9_tins  # old name, used by the W-9 tests


@asynccontextmanager
async def lifespan(app: FastAPI):
    from routes import blocks as blocks_routes, blog as blog_routes

    snapshot = None
    if core.DEV_DATABASE:
        import devdb

        snapshot = devdb.snapshot_path(core.MONGO_URL)
        await devdb.load(db, snapshot)
        logger.warning(f"Using the local dev database ({snapshot or 'memory only'}) — not for production")
    await ensure_indexes()
    await backfill_slot_keys()
    problem = await run_in_threadpool(storage.check)
    if problem:
        logger.error(f"File uploads won't work: {problem}")
    else:
        logger.info(f"File storage: {storage.BACKEND}")
    await seed_data()
    await blog_routes.seed_editorial_posts()
    await migrate_w9_tins()
    tasks = []
    if os.environ.get("DISABLE_BACKGROUND_WORKERS", "").lower() != "true":
        tasks = [asyncio.create_task(blocks_routes.email_outbox_worker()), asyncio.create_task(maintenance_loop())]
    if snapshot:
        tasks.append(asyncio.create_task(devdb.autosave_loop(db, snapshot)))
    yield
    for t in tasks:
        t.cancel()
    if snapshot:
        await devdb.save(db, snapshot)
    client.close()


app = FastAPI(title="Babybabel API", lifespan=lifespan)

# Browsers may only call the API from the app's own web origins. Native apps send no Origin
# header, so CORS doesn't affect them. Set CORS_ORIGINS (comma-separated) to your web app's
# address(es), e.g. https://babybabel.com. Local development servers are allowed by default.
_cors_origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]
if core.PUBLIC_WEB_URL and core.PUBLIC_WEB_URL not in _cors_origins:
    _cors_origins.append(core.PUBLIC_WEB_URL)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,  # the website's session cookie (origins below are explicit, never *)
    allow_origins=_cors_origins,
    allow_origin_regex=os.environ.get("CORS_ORIGIN_REGEX", r"^http://(localhost|127\.0\.0\.1)(:\d+)?$"),
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Stripe-Signature", "X-Babybabel-CSRF", "X-Session-Mode"],
)

api = APIRouter(prefix="/api")


@api.get("/")
async def root():
    return {"app": "Babybabel", "status": "ok"}


from routes import (  # noqa: E402  (routes import core, which must be configured first)
    admin, auth, blocks, blog, bookings, messages, notifications, parents, reviews, seo, tutors, uploads, w9,
)

for module in (auth, uploads, tutors, bookings, messages, reviews, parents, notifications, admin, seo, blog, w9, blocks):
    api.include_router(module.router)
app.include_router(api)

__all__ = ["app", "core", "db", "client", "decrypt_tin", "encrypt_tin", "is_legacy_tin_token", "_migrate_w9_tins"]
