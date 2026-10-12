from __future__ import annotations

import logging
from typing import Any

from ..config import Settings
from .base import DocumentStore
from .file_store import FileStore
from .mongo_store import MongoStore
from .seed_store import SeededStore

log = logging.getLogger("climate.store")


class SafeStore:
    """Wraps a primary store so a database outage degrades to cache misses
    (and re-computation) instead of failing the request."""

    def __init__(self, primary: DocumentStore, fallback: DocumentStore):
        self.primary, self.fallback = primary, fallback
        self.name = primary.name

    def get(self, collection: str, doc_id: str) -> dict[str, Any] | None:
        try:
            return self.primary.get(collection, doc_id)
        except Exception as exc:
            log.warning("primary store get failed (%s); using fallback", type(exc).__name__)
            return self.fallback.get(collection, doc_id)

    def put(self, collection: str, doc_id: str, doc: dict[str, Any], ttl_seconds: int) -> None:
        try:
            self.primary.put(collection, doc_id, doc, ttl_seconds)
        except Exception as exc:
            log.warning("primary store put failed (%s); writing fallback", type(exc).__name__)
            self.fallback.put(collection, doc_id, doc, ttl_seconds)

    def incr(self, collection: str, doc_id: str, ttl_seconds: int) -> int:
        try:
            return self.primary.incr(collection, doc_id, ttl_seconds)
        except Exception:
            return self.fallback.incr(collection, doc_id, ttl_seconds)


def build_store(settings: Settings) -> DocumentStore:
    file_store = FileStore(settings.data_dir)
    base: DocumentStore = file_store
    if settings.mongodb_uri:
        base = SafeStore(MongoStore(settings.mongodb_uri, settings.mongodb_db), file_store)
    return SeededStore(base, settings.seed_dir)
