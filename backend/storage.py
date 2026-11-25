"""File storage for uploads: a local folder, or any S3-compatible bucket.

STORAGE_BACKEND=local (default)  files live under STORAGE_DIR (default backend/data/uploads).
                                 Fine for development and a single server with a persistent disk.
STORAGE_BACKEND=s3               AWS S3, Cloudflare R2, Backblaze B2, MinIO, DigitalOcean Spaces…
                                 S3_BUCKET (required), S3_ENDPOINT_URL (for non-AWS providers),
                                 S3_REGION, and credentials via AWS_ACCESS_KEY_ID /
                                 AWS_SECRET_ACCESS_KEY (or an instance role).

All functions are synchronous — call them through run_in_threadpool from async code.
Paths are the app's own keys like "babybabel/uploads/<user>/<uuid>.jpg".
"""
import os
from pathlib import Path, PurePosixPath
from typing import Optional, Tuple

BACKEND = os.environ.get("STORAGE_BACKEND", "local").strip().lower()
LOCAL_DIR = Path(os.environ.get("STORAGE_DIR") or Path(__file__).parent / "data" / "uploads").resolve()


class StorageError(Exception):
    pass


class NotFound(StorageError):
    pass


def _safe_key(path: str) -> str:
    """Reject anything that could escape the storage root (.., absolute paths, backslashes)."""
    p = PurePosixPath(path)
    if not path or p.is_absolute() or "\\" in path or any(part in ("..", "") for part in p.parts):
        raise StorageError(f"invalid storage path: {path!r}")
    return str(p)


# ---- local folder ----
def _local_file(path: str) -> Path:
    f = (LOCAL_DIR / _safe_key(path)).resolve()
    if LOCAL_DIR not in f.parents:
        raise StorageError(f"invalid storage path: {path!r}")
    return f


def _local_put(path: str, data: bytes, content_type: str) -> None:
    f = _local_file(path)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f.name + ".part")
    tmp.write_bytes(data)
    tmp.replace(f)
    f.with_name(f.name + ".type").write_text(content_type, encoding="utf-8")


def _local_get(path: str) -> Tuple[bytes, str]:
    f = _local_file(path)
    if not f.is_file():
        raise NotFound(path)
    meta = f.with_name(f.name + ".type")
    ctype = meta.read_text(encoding="utf-8").strip() if meta.is_file() else "application/octet-stream"
    return f.read_bytes(), ctype


def _local_delete(path: str) -> bool:
    f = _local_file(path)
    for p in (f, f.with_name(f.name + ".type")):
        p.unlink(missing_ok=True)
    return True


# ---- S3-compatible bucket ----
_s3 = None


def _s3_client():
    global _s3
    if _s3 is None:
        import boto3  # imported lazily so local storage doesn't need it
        _s3 = boto3.client(
            "s3",
            endpoint_url=os.environ.get("S3_ENDPOINT_URL") or None,
            region_name=os.environ.get("S3_REGION") or None,
        )
    return _s3


def _bucket() -> str:
    bucket = os.environ.get("S3_BUCKET", "").strip()
    if not bucket:
        raise StorageError("STORAGE_BACKEND=s3 needs S3_BUCKET")
    return bucket


def _s3_put(path: str, data: bytes, content_type: str) -> None:
    _s3_client().put_object(Bucket=_bucket(), Key=_safe_key(path), Body=data, ContentType=content_type)


def _s3_get(path: str) -> Tuple[bytes, str]:
    try:
        obj = _s3_client().get_object(Bucket=_bucket(), Key=_safe_key(path))
    except Exception as e:  # botocore ClientError: NoSuchKey / 404
        code = getattr(e, "response", {}).get("Error", {}).get("Code", "")
        if code in ("NoSuchKey", "404", "NotFound"):
            raise NotFound(path) from e
        raise
    return obj["Body"].read(), obj.get("ContentType") or "application/octet-stream"


def _s3_delete(path: str) -> bool:
    _s3_client().delete_object(Bucket=_bucket(), Key=_safe_key(path))
    return True


# ---- public API ----
def put_object(path: str, data: bytes, content_type: str) -> None:
    (_s3_put if BACKEND == "s3" else _local_put)(path, data, content_type)


def get_object(path: str) -> Tuple[bytes, str]:
    """Returns (bytes, content_type). Raises NotFound if the file isn't there."""
    return (_s3_get if BACKEND == "s3" else _local_get)(path)


def delete_object(path: str) -> bool:
    """Best effort: returns False instead of raising, so account deletion never stops halfway."""
    try:
        return (_s3_delete if BACKEND == "s3" else _local_delete)(path)
    except Exception:
        return False


def check() -> Optional[str]:
    """Startup sanity check. Returns a problem description, or None if storage looks usable."""
    try:
        if BACKEND == "s3":
            _s3_client().head_bucket(Bucket=_bucket())
        elif BACKEND == "local":
            LOCAL_DIR.mkdir(parents=True, exist_ok=True)
        else:
            return f"unknown STORAGE_BACKEND={BACKEND!r} (use 'local' or 's3')"
    except Exception as e:
        return f"{BACKEND} storage not reachable: {e}"
    return None
