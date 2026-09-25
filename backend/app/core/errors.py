"""Domain exceptions mapped to HTTP problem responses."""

from __future__ import annotations


class DomainError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFound(DomainError):
    status_code = 404
    code = "not_found"


class Forbidden(DomainError):
    status_code = 403
    code = "forbidden"


class Unauthorized(DomainError):
    status_code = 401
    code = "unauthorized"


class Conflict(DomainError):
    status_code = 409
    code = "conflict"


class ValidationFailed(DomainError):
    status_code = 422
    code = "validation_failed"


class RateLimited(DomainError):
    status_code = 429
    code = "rate_limited"


class BudgetExceeded(DomainError):
    status_code = 402
    code = "budget_exceeded"


class UpstreamError(DomainError):
    status_code = 502
    code = "upstream_error"
