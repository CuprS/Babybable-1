"""Local development database: an in-process MongoDB stand-in that saves to a JSON file.

Use it by setting   MONGO_URL=memory://data/dev-db.json   (path relative to backend/).
`memory://` with no path keeps everything in memory only.

It lets you run the whole app on a laptop without installing MongoDB or Docker. It is NOT for
production: it's single-process, keeps everything in RAM, and saves on a timer and at shutdown.
Needs the dev dependency mongomock-motor (pip install -r requirements-dev.txt).
"""
import asyncio
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger("babybabel.devdb")
PREFIX = "memory://"


def is_dev_url(url: str) -> bool:
    return url.startswith(PREFIX)


def snapshot_path(url: str) -> Optional[Path]:
    rest = url[len(PREFIX):].strip()
    if not rest:
        return None
    p = Path(rest)
    return p if p.is_absolute() else (Path(__file__).parent / p).resolve()


def make_client():
    try:
        from mongomock_motor import AsyncMongoMockClient
    except ImportError as e:  # pragma: no cover - depends on the environment
        raise RuntimeError(
            "MONGO_URL=memory:// needs the dev dependencies: pip install -r requirements-dev.txt"
        ) from e
    return AsyncMongoMockClient()


async def load(db, path: Optional[Path]) -> int:
    """Restore a snapshot written by save(). Returns the number of documents loaded."""
    if not path or not path.is_file():
        return 0
    from bson import json_util

    data = json_util.loads(path.read_text(encoding="utf-8"))
    total = 0
    for name, docs in data.items():
        if docs:
            await db[name].insert_many(docs)
            total += len(docs)
    logger.info(f"dev database: loaded {total} documents from {path}")
    return total


async def save(db, path: Optional[Path]) -> None:
    if not path:
        return
    from bson import json_util

    data = {}
    for name in await db.list_collection_names():
        data[name] = await db[name].find({}).to_list(None)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json_util.dumps(data, indent=1), encoding="utf-8")
    os.replace(tmp, path)


async def autosave_loop(db, path: Optional[Path], every_seconds: int = 20) -> None:
    if not path:
        return
    while True:
        await asyncio.sleep(every_seconds)
        try:
            await save(db, path)
        except Exception as e:
            logger.error(f"dev database autosave failed: {e}")
