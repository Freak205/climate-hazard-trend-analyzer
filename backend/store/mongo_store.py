"""MongoDB document store (production backend). Works with the Atlas free tier.

Documents are stored with the app id as ``_id`` and an ``expires_at`` datetime
covered by a TTL index so MongoDB evicts stale cache entries on its own.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from pymongo import MongoClient, ReturnDocument


class MongoStore:
    name = "mongodb"

    def __init__(self, uri: str, db_name: str, client: Any | None = None):
        self.client = client or MongoClient(
            uri, serverSelectionTimeoutMS=4000, connectTimeoutMS=4000, tz_aware=True
        )
        self.db = self.client[db_name]
        self._indexed: set[str] = set()

    def _coll(self, collection: str):
        coll = self.db[collection]
        if collection not in self._indexed:
            try:
                coll.create_index("expires_at", expireAfterSeconds=0)
            except Exception:  # best-effort (limited permissions / test doubles)
                pass
            self._indexed.add(collection)
        return coll

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    def get(self, collection: str, doc_id: str) -> dict[str, Any] | None:
        row = self._coll(collection).find_one({"_id": doc_id})
        if not row:
            return None
        expires = row.get("expires_at")
        if expires is not None:
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if expires < self._now():
                return None
        return row.get("doc")

    def put(self, collection: str, doc_id: str, doc: dict[str, Any], ttl_seconds: int) -> None:
        self._coll(collection).replace_one(
            {"_id": doc_id},
            {"_id": doc_id, "doc": doc, "expires_at": self._now() + timedelta(seconds=ttl_seconds)},
            upsert=True,
        )

    def incr(self, collection: str, doc_id: str, ttl_seconds: int) -> int:
        row = self._coll(collection).find_one_and_update(
            {"_id": doc_id},
            {"$inc": {"n": 1}, "$setOnInsert": {"expires_at": self._now() + timedelta(seconds=ttl_seconds)}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return int(row["n"])
