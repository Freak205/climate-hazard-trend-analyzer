"""Rate limiting.

Two layers, because serverless instances do not share memory:

  * ``BurstLimiter``  - cheap in-memory fixed window per client, protects each
                        instance from request floods (per-minute budget).
  * ``IngestLimiter`` - counts *expensive* actions (calls that hit the upstream
                        weather API) in the shared document store (MongoDB when
                        configured, so it is global; per-instance file store
                        otherwise). Cache hits are never counted.
"""
from __future__ import annotations

import hashlib
import os
import threading
import time

from fastapi import Request

from .errors import RateLimited
from .store.base import DocumentStore


def client_id(request: Request) -> str:
    """Hashed client identifier (we never persist raw IP addresses)."""
    ip = None
    if os.environ.get("VERCEL"):  # behind Vercel's proxy the forwarded header is set by the platform
        fwd = request.headers.get("x-vercel-forwarded-for") or request.headers.get("x-forwarded-for")
        if fwd:
            ip = fwd.split(",")[0].strip()
    ip = ip or (request.client.host if request.client else "unknown")
    return hashlib.sha256(ip.encode()).hexdigest()[:16]


class BurstLimiter:
    def __init__(self, limit: int, window_seconds: int = 60, max_clients: int = 5000):
        self.limit, self.window, self.max_clients = limit, window_seconds, max_clients
        self._hits: dict[str, tuple[int, int]] = {}  # client -> (window index, count)
        self._lock = threading.Lock()

    def check(self, client: str) -> tuple[int, int]:
        """Raises RateLimited when over budget; returns (remaining, reset_in_seconds)."""
        now = time.time()
        window = int(now // self.window)
        reset = int((window + 1) * self.window - now) + 1
        with self._lock:
            if len(self._hits) > self.max_clients:  # bounded memory under a distributed flood
                self._hits = {k: v for k, v in self._hits.items() if v[0] == window}
            w, count = self._hits.get(client, (window, 0))
            if w != window:
                count = 0
            count += 1
            self._hits[client] = (window, count)
        if count > self.limit:
            raise RateLimited("Too many requests. Please slow down.", retry_after=reset)
        return self.limit - count, reset


class IngestLimiter:
    def __init__(self, store: DocumentStore, per_hour: int, bucket: str = "ingest"):
        self.store, self.per_hour, self.bucket = store, per_hour, bucket

    def check(self, client: str) -> None:
        window = int(time.time() // 3600)
        n = self.store.incr("rate_limits", f"{self.bucket}|{client}|{window}", 2 * 3600)
        if n > self.per_hour:
            reset = int((window + 1) * 3600 - time.time()) + 1
            raise RateLimited(
                f"Limit of {self.per_hour} uncached {self.bucket} requests per hour reached. "
                "Regions that are already cached are not limited.",
                retry_after=reset,
            )
