"""ORM -> JSON-able dict helpers."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import inspect

_SENSITIVE = {"password_hash", "key_hash", "destinations_encrypted", "credentials_encrypted", "embedding", "tsv"}


def _val(v: Any) -> Any:
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, datetime | date):
        return v.isoformat()
    if isinstance(v, list):
        return [_val(x) for x in v]
    if isinstance(v, dict):
        return {k: _val(x) for k, x in v.items()}
    return v


def row(obj: Any, *, exclude: set[str] | None = None, include: set[str] | None = None) -> dict[str, Any]:
    if obj is None:
        return {}
    mapper = inspect(obj).mapper
    out = {}
    skip = _SENSITIVE | (exclude or set())
    for col in mapper.column_attrs:
        k = col.key
        if k in skip or (include and k not in include):
            continue
        out[k] = _val(getattr(obj, k))
    return out


def rows(objs: list[Any], **kw: Any) -> list[dict[str, Any]]:
    return [row(o, **kw) for o in objs]
