"""File uploads and gated downloads."""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

import storage
from core import APP_NAME, MAX_UPLOAD_BYTES, _user_from_token, current_user, db, logger, now_iso, oauth2_scheme

router = APIRouter()

# The stored content type is derived from the extension, never from the client, so an
# uploaded file can't be served back as HTML/JS (stored XSS on the API origin).
UPLOAD_TYPES = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp",
    "heic": "image/heic", "heif": "image/heif",
    "pdf": "application/pdf", "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "rtf": "application/rtf", "txt": "text/plain; charset=utf-8",
}


@router.post("/uploads")
async def upload(file: UploadFile = File(...), u: dict = Depends(current_user)):
    ext = (file.filename or "file").rsplit(".", 1)[-1].lower()
    if ext not in UPLOAD_TYPES:
        ext = "jpg"
    path = f"{APP_NAME}/uploads/{u['id']}/{uuid.uuid4()}.{ext}"
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"File is too large (max {MAX_UPLOAD_BYTES // (1024 * 1024)} MB)")
    if not data:
        raise HTTPException(400, "The file is empty")
    ctype = UPLOAD_TYPES[ext]
    try:
        await run_in_threadpool(storage.put_object, path, data, ctype)
    except Exception as e:
        logger.exception("upload failed")
        raise HTTPException(502, f"Upload failed: {e}")
    await db.uploads.insert_one({"path": path, "owner_id": u["id"], "content_type": ctype, "created_at": now_iso()})
    return {"path": path, "url": f"/api/files/{path}", "content_type": ctype}


async def _file_access(path: str) -> tuple[str, Optional[str]]:
    """Classify a stored file by who references it.
    - owner_only: children photos, identity documents, background checks (owner + admins)
    - signed_in: tutor accreditation documents/photos (any signed-in user)
    - public: everything else (avatars, hero images, blog photos)
    Returns (level, owner_user_id)."""
    child_ref = await db.parents.find_one({"children.avatar_url": path}, {"_id": 0, "user_id": 1})
    if child_ref:
        return "owner_only", child_ref["user_id"]
    identity_ref = await db.tutors.find_one(
        {"$or": [{"id_document_url": path}, {"background_check_url": path}]}, {"_id": 0, "user_id": 1})
    if identity_ref:
        return "owner_only", identity_ref["user_id"]
    accreditation_ref = await db.tutors.find_one(
        {"$or": [{"accreditation_photo_url": path}, {"accreditation_document_url": path}, {"accreditation_urls": path}]},
        {"_id": 0, "user_id": 1},
    )
    if accreditation_ref:
        return "signed_in", accreditation_ref["user_id"]
    return "public", None


@router.get("/files/{path:path}")
async def get_file(path: str, token: Optional[str] = Depends(oauth2_scheme)):
    rec = await db.uploads.find_one({"path": path}, {"_id": 0})
    if not rec:
        raise HTTPException(404, "File not found")
    level, owner = await _file_access(path)
    caller = await _user_from_token(token)  # Authorization header only — never tokens in the URL
    if level == "owner_only":
        if not caller:
            raise HTTPException(401, "Auth required for private file")
        if caller["id"] != owner and not caller.get("is_admin"):
            raise HTTPException(403, "Not your file")
    elif level == "signed_in" and not caller:
        raise HTTPException(401, "Auth required to view accreditation documents")
    try:
        content, ctype = await run_in_threadpool(storage.get_object, path)
    except storage.NotFound:
        raise HTTPException(404, "File not found")
    except Exception as e:
        logger.exception("download failed")
        raise HTTPException(502, f"Download failed: {e}")
    # Never let a shared cache/CDN store gated files.
    headers = {
        "Cache-Control": "public, max-age=86400" if level == "public" else "private, no-store",
        "X-Content-Type-Options": "nosniff",
    }
    # Older uploads stored a client-supplied type; anything off the allow-list is
    # downloaded rather than rendered, so it can never run script in the browser.
    if ctype not in UPLOAD_TYPES.values():
        headers["Content-Disposition"] = "attachment"
        ctype = "application/octet-stream"
    return Response(content=content, media_type=ctype, headers=headers)
