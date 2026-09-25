"""Per-request context (request id, client ip) propagated via contextvars."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

_request_meta: ContextVar[dict[str, Any] | None] = ContextVar("request_meta", default=None)


def set_request_meta(meta: dict[str, Any]) -> None:
    _request_meta.set(meta)


def current_request_meta() -> dict[str, Any]:
    return _request_meta.get() or {}
