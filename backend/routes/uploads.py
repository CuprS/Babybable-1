"""File uploads and gated downloads."""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

import storage
from core import (
    APP_NAME, FILE_URL_MINUTES, MAX_UPLOAD_BYTES, _user_from_token, current_user, db, file_signature_ok, logger,
    now_iso, request_token, signed_file_url,
)

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


async def _file_access(path: str, owner_id: Optional[str]) -> tuple[str, Optional[str]]:
    """Classify a stored file by who references it.
    - owner_only: children photos, identity documents, background checks, and any upload not yet
      used anywhere (owner + admins)
    - signed_in: tutor accreditation documents/photos (any signed-in user)
    - public: profile photos, tutors' cover images, blog photos
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
    public_ref = (
        await db.users.find_one({"avatar_url": path}, {"_id": 1})
        or await db.parents.find_one({"avatar_url": path}, {"_id": 1})
        or await db.tutors.find_one({"$or": [{"avatar_url": path}, {"hero_image_url": path}]}, {"_id": 1})
        or await db.posts.find_one({"$or": [{"cover_image_url": path}, {"image_urls": path}]}, {"_id": 1})
    )
    if public_ref:
        return "public", None
    return "owner_only", owner_id  # uploaded but not used anywhere (yet)


def _allowed(level: str, owner: Optional[str], caller: Optional[dict]) -> tuple[bool, int]:
    if level == "public":
        return True, 200
    if not caller:
        return False, 401
    if level == "signed_in" or caller["id"] == owner or caller.get("is_admin"):
        return True, 200
    return False, 403


@router.get("/files-link")
async def file_link(path: str, u: dict = Depends(current_user)):
    """A short-lived link for showing a file the caller may see (private images can't send headers)."""
    path = path.split("/api/files/", 1)[-1].split("?", 1)[0]
    rec = await db.uploads.find_one({"path": path}, {"_id": 0, "owner_id": 1})
    if not rec:
        raise HTTPException(404, "File not found")
    level, owner = await _file_access(path, rec.get("owner_id"))
    ok, code = _allowed(level, owner, u)
    if not ok:
        raise HTTPException(code, "Not your file")
    return {"url": f"/api/files/{path}" if level == "public" else signed_file_url(path), "expires_in": None if level == "public" else FILE_URL_MINUTES * 60}


@router.get("/files/{path:path}")
async def get_file(path: str, exp: Optional[str] = None, sig: Optional[str] = None,
                   token: Optional[str] = Depends(request_token)):
    rec = await db.uploads.find_one({"path": path}, {"_id": 0})
    if not rec:
        raise HTTPException(404, "File not found")
    level, owner = await _file_access(path, rec.get("owner_id"))
    if not file_signature_ok(path, exp, sig):  # a valid signed link already proves access
        caller = await _user_from_token(token)  # header or session cookie — never tokens in the URL
        ok, code = _allowed(level, owner, caller)
        if not ok:
            raise HTTPException(code, "Sign in to see this file" if code == 401 else "Not your file")
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
