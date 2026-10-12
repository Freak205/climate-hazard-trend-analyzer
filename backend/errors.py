"""Typed errors that map 1:1 onto clean JSON API responses."""
from __future__ import annotations


class ApiError(Exception):
    status = 500
    code = "internal_error"

    def __init__(self, message: str, *, retry_after: int | None = None):
        super().__init__(message)
        self.message = message
        self.retry_after = retry_after


class BadRequest(ApiError):
    status, code = 400, "bad_request"


class RateLimited(ApiError):
    status, code = 429, "rate_limited"


class UpstreamUnavailable(ApiError):
    status, code = 502, "upstream_unavailable"


class UpstreamRateLimited(ApiError):
    status, code = 503, "upstream_rate_limited"


class InsufficientData(ApiError):
    status, code = 422, "insufficient_data"
