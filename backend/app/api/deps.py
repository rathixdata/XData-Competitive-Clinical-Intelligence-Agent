"""FastAPI dependencies: authentication, tenant-scoped sessions, RBAC, rate limits, idempotency."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, Header, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.crypto import sha256_hex, stable_json
from app.core.errors import Conflict, RateLimited, Unauthorized
from app.core.rbac import Perm
from app.core.security import Principal, authenticate_bearer
from app.db.session import new_session
from app.models import IdempotencyRecord

_bearer = HTTPBearer(auto_error=False)


def get_principal(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> Principal:
    if creds is None or not creds.credentials:
        raise Unauthorized("missing bearer token")
    return authenticate_bearer(creds.credentials)


def get_db(principal: Principal = Depends(get_principal)) -> Iterator[Session]:
    """Session bound to the caller's tenant: Postgres RLS enforces isolation for every query."""
    db = new_session(principal.tenant_id, bypass_rls=False)
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def require(perm: Perm) -> Callable[[Principal], Principal]:
    def _dep(principal: Principal = Depends(get_principal)) -> Principal:
        principal.require(perm)
        return principal

    return _dep


# ------------------------------------------------------------------ rate limiting
class _Limiter:
    """Fixed-window limiter backed by Redis (shared across replicas) with in-process fallback."""

    def __init__(self) -> None:
        self._local: dict[str, tuple[int, int]] = {}
        self._redis: Any = None
        self._checked = False

    def _r(self) -> Any:
        if not self._checked:
            self._checked = True
            try:
                import redis

                r = redis.Redis.from_url(get_settings().redis_url, socket_timeout=0.3)
                r.ping()
                self._redis = r
            except Exception:  # noqa: BLE001
                self._redis = None
        return self._redis

    def hit(self, key: str, limit: int, window: int = 60) -> bool:
        bucket = int(time.time() // window)
        r = self._r()
        if r is not None:
            try:
                k = f"xdata:api:{key}:{bucket}"
                n = r.incr(k)
                if n == 1:
                    r.expire(k, window + 5)
                return int(n) <= limit
            except Exception:  # noqa: BLE001, S110 - Redis hiccup: fall back to local window
                self._redis = None
        b, n = self._local.get(key, (bucket, 0))
        n = n + 1 if b == bucket else 1
        self._local[key] = (bucket, n)
        return n <= limit


limiter = _Limiter()


def rate_limit(kind: str = "api") -> Callable[[Principal], Principal]:
    def _dep(principal: Principal = Depends(get_principal)) -> Principal:
        s = get_settings()
        limit = s.ask_rate_limit_per_minute if kind == "ask" else s.api_rate_limit_per_minute
        if not limiter.hit(f"{kind}:{principal.tenant_id}:{principal.user_id}", limit):
            raise RateLimited(f"rate limit exceeded ({limit}/min)")
        return principal

    return _dep


# ------------------------------------------------------------------ pagination
@dataclass
class Page:
    limit: int
    offset: int


def page_params(limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)) -> Page:
    return Page(limit, offset)


def paged(items: list[Any], total: int, page: Page) -> dict[str, Any]:
    return {"items": items, "total": total, "limit": page.limit, "offset": page.offset,
            "next_offset": page.offset + page.limit if page.offset + page.limit < total else None}


# ------------------------------------------------------------------ idempotency
@dataclass
class Idempotency:
    key: str | None
    request_hash: str
    principal: Principal

    def replay(self, db: Session) -> Any | None:
        if not self.key:
            return None
        rec = db.get(IdempotencyRecord, (self.key, self.principal.tenant_id))
        if rec is None:
            return None
        if rec.request_hash != self.request_hash:
            raise Conflict("Idempotency-Key reused with a different request body")
        return rec.response

    def store(self, db: Session, request: Request, response: Any, status_code: int = 200) -> None:
        if not self.key:
            return
        db.add(IdempotencyRecord(key=self.key, tenant_id=self.principal.tenant_id, method=request.method,
                                 path=request.url.path, request_hash=self.request_hash, status_code=status_code,
                                 response=json.loads(json.dumps(response, default=str))))
        db.flush()


async def idempotency(request: Request, principal: Principal = Depends(get_principal),
                      idempotency_key: str | None = Header(None, alias="Idempotency-Key")) -> Idempotency:
    body = await request.body()
    try:
        canonical = stable_json(json.loads(body)) if body else ""
    except ValueError:
        canonical = body.decode("utf-8", "replace")
    return Idempotency(idempotency_key[:200] if idempotency_key else None,
                       sha256_hex(f"{request.method}:{request.url.path}:{canonical}"), principal)
