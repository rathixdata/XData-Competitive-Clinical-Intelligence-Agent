"""Authentication endpoints: local login (bootstrap / non-SSO tenants), identity, API keys."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_principal, limiter
from app.api.serialize import row, rows
from app.core.config import get_settings
from app.core.crypto import generate_api_key, verify_password
from app.core.errors import NotFound, RateLimited, Unauthorized, ValidationFailed
from app.core.rbac import ALL_ROLES
from app.core.security import Principal, issue_access_token
from app.db.session import session_scope
from app.models import ApiKey, Tenant, User
from app.services import audit

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    tenant: str = Field(..., description="Tenant slug")
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=512)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105
    expires_in: int


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn) -> TokenOut:
    s = get_settings()
    if not s.local_auth_enabled:
        raise Unauthorized("local login disabled; use SSO")
    if not limiter.hit(f"login:{body.tenant}:{body.email.lower()}", s.login_rate_limit_per_minute):
        raise RateLimited("too many login attempts")
    with session_scope(bypass_rls=True) as db:
        tenant = db.scalar(select(Tenant).where(Tenant.slug == body.tenant, Tenant.status == "active"))
        user = db.scalar(select(User).where(User.tenant_id == tenant.id, User.email == body.email.lower())) if tenant else None
        if user is None or not user.is_active or not user.password_hash or not verify_password(body.password, user.password_hash):
            audit.record(db, action="auth.login_failed", resource_type="user", resource_id=body.email.lower(),
                         tenant_id=tenant.id if tenant else None, actor_id=body.email.lower(), actor_type="anonymous")
            raise Unauthorized("invalid credentials")
        user.last_login_at = datetime.now(UTC)
        token, ttl = issue_access_token(user)
        audit.record(db, action="auth.login", resource_type="user", resource_id=user.id, tenant_id=user.tenant_id,
                     actor_id=str(user.id))
        return TokenOut(access_token=token, expires_in=ttl)


@router.get("/me")
def me(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)) -> dict:
    user = db.get(User, principal.user_id)
    tenant = db.get(Tenant, principal.tenant_id)
    return {
        "user": row(user, exclude={"preferences"}) if user else {"id": str(principal.user_id), "email": principal.email},
        "tenant": {"id": str(tenant.id), "name": tenant.name, "slug": tenant.slug,
                   "deployment_mode": tenant.deployment_mode} if tenant else None,
        "roles": list(principal.roles),
        "permissions": sorted(p.value for p in principal.permissions),
        "auth_method": principal.auth_method,
        "available_roles": list(ALL_ROLES),
    }


@router.get("/ai-transparency", tags=["ai"])
def ai_transparency(principal: Principal = Depends(get_principal)) -> dict:
    """AI transparency / model card: purpose, components, oversight, limits, evaluation (XAI)."""
    from app.ai.explain import transparency_card

    return transparency_card()


class ApiKeyIn(BaseModel):
    name: str = Field(..., max_length=100)
    roles: list[str] = Field(default_factory=list, description="Subset of the owner's roles; empty = all")
    expires_in_days: int | None = Field(90, ge=1, le=365)


@router.post("/api-keys", status_code=201)
def create_api_key(body: ApiKeyIn, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)) -> dict:
    bad = [r for r in body.roles if r not in principal.roles]
    if bad:
        raise ValidationFailed(f"cannot grant roles you do not hold: {bad}")
    key, prefix, digest = generate_api_key()
    rec = ApiKey(tenant_id=principal.tenant_id, user_id=principal.user_id, name=body.name, key_prefix=prefix,
                 key_hash=digest, roles=body.roles,
                 expires_at=datetime.now(UTC) + timedelta(days=body.expires_in_days) if body.expires_in_days else None)
    db.add(rec)
    db.flush()
    audit.record(db, action="api_key.create", resource_type="api_key", resource_id=rec.id,
                 tenant_id=principal.tenant_id, actor_id=principal.actor, after={"name": body.name, "roles": body.roles})
    return {"id": str(rec.id), "key": key, "note": "Store this key now; it cannot be shown again.",
            "expires_at": rec.expires_at}


@router.get("/api-keys")
def list_api_keys(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)) -> list[dict]:
    return rows(db.scalars(select(ApiKey).where(ApiKey.user_id == principal.user_id)).all())


@router.delete("/api-keys/{key_id}", status_code=204)
def revoke_api_key(key_id: uuid.UUID, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)) -> None:
    rec = db.get(ApiKey, key_id)
    if rec is None or rec.user_id != principal.user_id:
        raise NotFound("api key not found")
    rec.revoked_at = datetime.now(UTC)
    audit.record(db, action="api_key.revoke", resource_type="api_key", resource_id=rec.id,
                 tenant_id=principal.tenant_id, actor_id=principal.actor)
