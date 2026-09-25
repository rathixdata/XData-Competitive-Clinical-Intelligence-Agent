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


def redact_provenance(d: dict[str, Any], *, platform_admin: bool) -> dict[str, Any]:
    """Shared public-corpus rows carry fetch provenance aggregated across tenants (e.g. PubMed queries and
    landscape ids). Only platform administrators may see it; tenants get the non-identifying parts."""
    if platform_admin:
        return d
    out = dict(d)
    qp = out.get("query_provenance")
    if isinstance(qp, dict):
        out["query_provenance"] = {k: v for k, v in qp.items() if k in ("mode", "dataset", "esearch")}
    elif isinstance(qp, list):
        out["query_provenance"] = [{k: v for k, v in x.items() if k in ("mode", "dataset", "esearch")}
                                   for x in qp if isinstance(x, dict)]
    return out
