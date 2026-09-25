"""Authentication: local JWT, enterprise OIDC/SSO bearer tokens, and API keys (NFR-SEC-002)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

import jwt
from sqlalchemy import select

from app.core.config import get_settings
from app.core.crypto import sha256_hex
from app.core.errors import Forbidden, Unauthorized
from app.core.rbac import Perm, permissions_for
from app.db.session import session_scope
from app.models import ApiKey, Tenant, User


@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    email: str
    roles: tuple[str, ...]
    team: str | None = None
    auth_method: str = "local"  # local | oidc | api_key
    permissions: frozenset[Perm] = field(default_factory=frozenset)

    @property
    def actor(self) -> str:
        return str(self.user_id)

    def has(self, perm: Perm) -> bool:
        return perm in self.permissions

    def require(self, perm: Perm) -> None:
        if perm not in self.permissions:
            raise Forbidden(f"missing permission {perm.value}")


def issue_access_token(user: User) -> tuple[str, int]:
    s = get_settings()
    ttl = s.access_token_ttl_minutes * 60
    now = datetime.now(UTC)
    payload = {
        "sub": str(user.id),
        "tid": str(user.tenant_id),
        "email": user.email,
        "roles": list(user.roles or []),
        "iss": s.jwt_issuer,
        "aud": s.jwt_audience,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl)).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, s.jwt_secret.get_secret_value(), algorithm="HS256"), ttl


@lru_cache
def _jwks_client(url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(url, cache_keys=True, lifespan=3600)


def _principal_from_user(user: User, method: str, roles: list[str] | None = None) -> Principal:
    r = tuple(roles if roles is not None else (user.roles or []))
    return Principal(
        user_id=user.id,
        tenant_id=user.tenant_id,
        email=user.email,
        roles=r,
        team=user.team,
        auth_method=method,
        permissions=frozenset(permissions_for(r)),
    )


def _authenticate_local_jwt(token: str) -> Principal:
    s = get_settings()
    try:
        claims = jwt.decode(
            token,
            s.jwt_secret.get_secret_value(),
            algorithms=["HS256"],
            audience=s.jwt_audience,
            issuer=s.jwt_issuer,
            options={"require": ["exp", "sub", "tid"]},
        )
    except jwt.PyJWTError as e:
        raise Unauthorized("invalid or expired token") from e
    with session_scope(bypass_rls=True) as db:
        user = db.get(User, uuid.UUID(claims["sub"]))
        if user is None or not user.is_active or str(user.tenant_id) != claims["tid"]:
            raise Unauthorized("user inactive or not found")
        tenant = db.get(Tenant, user.tenant_id)
        if tenant is None or tenant.status != "active":
            raise Unauthorized("tenant inactive")
        return _principal_from_user(user, "local")


def _authenticate_oidc(token: str) -> Principal:
    s = get_settings()
    assert s.oidc_jwks_url and s.oidc_issuer
    try:
        signing_key = _jwks_client(s.oidc_jwks_url).get_signing_key_from_jwt(token)
        claims: dict[str, Any] = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "ES256", "PS256"],
            audience=s.oidc_audience,
            issuer=s.oidc_issuer,
        )
    except jwt.PyJWTError as e:
        raise Unauthorized("invalid SSO token") from e
    if s.oidc_require_mfa:
        amr = claims.get("amr") or []
        if not ({"mfa", "otp", "hwk", "swk"} & set(amr)):
            raise Unauthorized("MFA required by policy")
    tenant_slug = claims.get(s.oidc_tenant_claim)
    if not tenant_slug:
        raise Unauthorized("token missing tenant claim")
    with session_scope(bypass_rls=True) as db:
        tenant = db.scalar(select(Tenant).where(Tenant.slug == tenant_slug, Tenant.status == "active"))
        if tenant is None:
            raise Unauthorized("unknown tenant")
        user = db.scalar(select(User).where(User.tenant_id == tenant.id, User.external_subject == claims["sub"]))
        email = claims.get("email") or claims.get("preferred_username") or claims["sub"]
        idp_roles = [r for r in (claims.get(s.oidc_roles_claim) or []) if isinstance(r, str)]
        if user is None:
            # Just-in-time provisioning; roles come from the IdP (least privilege default: viewer)
            user = User(
                tenant_id=tenant.id,
                email=email,
                display_name=claims.get("name") or email,
                external_subject=claims["sub"],
                roles=idp_roles or ["viewer"],
            )
            db.add(user)
            db.flush()
        elif idp_roles:
            user.roles = idp_roles
        if not user.is_active:
            raise Unauthorized("user disabled")
        user.last_login_at = datetime.now(UTC)
        return _principal_from_user(user, "oidc")


def _authenticate_api_key(key: str) -> Principal:
    prefix = key.removeprefix("xdk_")[:8]
    digest = sha256_hex(key)
    with session_scope(bypass_rls=True) as db:
        rec = db.scalar(select(ApiKey).where(ApiKey.key_prefix == prefix, ApiKey.key_hash == digest))
        now = datetime.now(UTC)
        if rec is None or rec.revoked_at is not None or (rec.expires_at and rec.expires_at < now):
            raise Unauthorized("invalid API key")
        user = db.get(User, rec.user_id)
        if user is None or not user.is_active:
            raise Unauthorized("API key owner inactive")
        rec.last_used_at = now
        # API keys may only narrow the owner's roles
        roles = [r for r in rec.roles if r in (user.roles or [])] if rec.roles else list(user.roles or [])
        return _principal_from_user(user, "api_key", roles)


def authenticate_bearer(token: str) -> Principal:
    s = get_settings()
    if token.startswith("xdk_"):
        return _authenticate_api_key(token)
    if s.oidc_jwks_url:
        try:
            unverified = jwt.decode(token, options={"verify_signature": False})
        except jwt.PyJWTError as e:
            raise Unauthorized("malformed token") from e
        if unverified.get("iss") == s.oidc_issuer:
            return _authenticate_oidc(token)
    if not s.local_auth_enabled:
        raise Unauthorized("local authentication disabled")
    return _authenticate_local_jwt(token)


def system_principal(tenant_id: uuid.UUID) -> Principal:
    from app.core.rbac import ROLE_PERMISSIONS

    return Principal(
        user_id=uuid.UUID(int=0),
        tenant_id=tenant_id,
        email="system@xdata",
        roles=("system",),
        auth_method="system",
        permissions=frozenset(ROLE_PERMISSIONS["tenant_admin"]),
    )
