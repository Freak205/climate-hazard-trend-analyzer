"""Document-store interface. The app only needs get/put with a TTL, which maps
naturally onto any NoSQL backend (MongoDB, Firestore, DynamoDB, Redis...)."""
from __future__ import annotations

from typing import Any, Protocol


class DocumentStore(Protocol):
    name: str

    def get(self, collection: str, doc_id: str) -> dict[str, Any] | None: ...

    def put(self, collection: str, doc_id: str, doc: dict[str, Any], ttl_seconds: int) -> None: ...

    def incr(self, collection: str, doc_id: str, ttl_seconds: int) -> int:
        """Atomically increment a counter document (used for rate limits)."""
        ...
