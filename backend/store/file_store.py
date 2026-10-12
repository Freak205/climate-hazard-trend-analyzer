"""JSON-file document store: one file per document, grouped by collection.

Used when no MongoDB is configured (local dev, and as a per-instance cache on
Vercel where only /tmp is writable). Writes are atomic (tmp file + rename).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

_SAFE = re.compile(r"[^A-Za-z0-9_.-]")


class FileStore:
    name = "file"

    def __init__(self, root: str):
        self.root = Path(root)
        self._lock = threading.Lock()

    def _path(self, collection: str, doc_id: str) -> Path:
        safe = _SAFE.sub("_", collection)
        digest = hashlib.sha1(doc_id.encode()).hexdigest()[:10]
        return self.root / safe / f"{_SAFE.sub('_', doc_id)[:80]}-{digest}.json"

    def _read(self, path: Path) -> dict[str, Any] | None:
        try:
            with path.open("r", encoding="utf-8") as fh:
                wrapper = json.load(fh)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None
        if wrapper.get("expires_at", 0) < time.time():
            return None
        return wrapper

    def _write(self, path: Path, wrapper: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(wrapper, fh, separators=(",", ":"))
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def get(self, collection: str, doc_id: str) -> dict[str, Any] | None:
        wrapper = self._read(self._path(collection, doc_id))
        return wrapper["doc"] if wrapper else None

    def put(self, collection: str, doc_id: str, doc: dict[str, Any], ttl_seconds: int) -> None:
        self._write(self._path(collection, doc_id), {"expires_at": time.time() + ttl_seconds, "doc": doc})

    def incr(self, collection: str, doc_id: str, ttl_seconds: int) -> int:
        path = self._path(collection, doc_id)
        with self._lock:
            wrapper = self._read(path)
            if wrapper is None:  # first hit in this window: start the TTL clock
                wrapper = {"expires_at": time.time() + ttl_seconds, "doc": {"n": 0}}
            wrapper["doc"]["n"] += 1
            self._write(path, wrapper)
            return wrapper["doc"]["n"]
