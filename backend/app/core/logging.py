"""Structured logging with secret redaction (NFR-OBS-001, NFR-SEC-004)."""

from __future__ import annotations

import logging
import re
import sys
from typing import Any

import structlog

from app.core.config import get_settings

_SENSITIVE_KEYS = re.compile(
    r"(authorization|password|passwd|secret|token|api[_-]?key|cookie|set-cookie|credential|webhook_url)",
    re.IGNORECASE,
)
_BEARER = re.compile(r"(Bearer\s+)[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE)
_KEYLIKE = re.compile(r"\b(sk-[A-Za-z0-9\-_]{12,}|pa-[A-Za-z0-9\-_]{12,})\b")


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        value = _BEARER.sub(r"\1[REDACTED]", value)
        return _KEYLIKE.sub("[REDACTED]", value)
    if isinstance(value, dict):
        return {k: ("[REDACTED]" if _SENSITIVE_KEYS.search(str(k)) else _redact_value(v)) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return type(value)(_redact_value(v) for v in value)
    return value


def redact_processor(_logger: Any, _method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    return {k: ("[REDACTED]" if _SENSITIVE_KEYS.search(k) else _redact_value(v)) for k, v in event_dict.items()}


def configure_logging() -> None:
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level, force=True)
    for noisy in ("httpx", "httpcore", "urllib3", "botocore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    renderer: Any = (
        structlog.processors.JSONRenderer() if settings.log_json else structlog.dev.ConsoleRenderer(colors=False)
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            redact_processor,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
