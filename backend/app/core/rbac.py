"""Role-based access control (NFR-SEC-003). Enforced server-side on every protected operation."""

from __future__ import annotations

from enum import StrEnum


class Perm(StrEnum):
    LANDSCAPE_READ = "landscape:read"
    LANDSCAPE_WRITE = "landscape:write"
    WATCHLIST_WRITE = "watchlist:write"
    ENTITY_READ = "entity:read"
    ENTITY_CURATE = "entity:curate"  # approve / reject / merge / split matches, aliases
    EVENT_READ = "event:read"
    EVENT_TRIAGE = "event:triage"  # acknowledge / escalate
    NARRATIVE_EDIT = "narrative:edit"  # editorial override (FR-FBK-002)
    FEEDBACK_WRITE = "feedback:write"
    ASK = "ask:use"
    ALERT_WRITE = "alert:write"
    REPORT_READ = "report:read"
    REPORT_WRITE = "report:write"
    REPORT_APPROVE = "report:approve"
    SOURCE_READ = "source:read"
    CONNECTOR_ADMIN = "connector:admin"
    CONFIG_ADMIN = "config:admin"  # thresholds, proximity rules, profile fields, model releases
    USER_ADMIN = "user:admin"
    AUDIT_READ = "audit:read"
    AUDIT_EXPORT = "audit:export"
    TRAINING_DATA = "training:curate"
    PLATFORM_ADMIN = "platform:admin"


_READER = {
    Perm.LANDSCAPE_READ,
    Perm.ENTITY_READ,
    Perm.EVENT_READ,
    Perm.FEEDBACK_WRITE,
    Perm.ASK,
    Perm.REPORT_READ,
    Perm.SOURCE_READ,
    Perm.WATCHLIST_WRITE,
    Perm.ALERT_WRITE,
}
_ANALYST = _READER | {
    Perm.LANDSCAPE_WRITE,
    Perm.ENTITY_CURATE,
    Perm.EVENT_TRIAGE,
    Perm.NARRATIVE_EDIT,
    Perm.REPORT_WRITE,
}

ROLE_PERMISSIONS: dict[str, set[Perm]] = {
    "viewer": {Perm.LANDSCAPE_READ, Perm.ENTITY_READ, Perm.EVENT_READ, Perm.REPORT_READ, Perm.SOURCE_READ},
    "executive": _READER,
    "clinical_strategy": _READER | {Perm.EVENT_TRIAGE},
    "portfolio_strategy": _READER | {Perm.EVENT_TRIAGE},
    "medical_affairs": _READER | {Perm.EVENT_TRIAGE},
    "regulatory_affairs": _READER | {Perm.EVENT_TRIAGE},
    "business_development": _READER,
    "ci_analyst": _ANALYST,
    "ci_lead": _ANALYST | {Perm.REPORT_APPROVE, Perm.TRAINING_DATA},
    "auditor": {Perm.AUDIT_READ, Perm.AUDIT_EXPORT, Perm.LANDSCAPE_READ, Perm.EVENT_READ, Perm.REPORT_READ},
    "tenant_admin": _ANALYST
    | {
        Perm.REPORT_APPROVE,
        Perm.CONNECTOR_ADMIN,
        Perm.CONFIG_ADMIN,
        Perm.USER_ADMIN,
        Perm.AUDIT_READ,
        Perm.AUDIT_EXPORT,
        Perm.TRAINING_DATA,
    },
    "platform_admin": set(Perm),
}

ALL_ROLES = tuple(ROLE_PERMISSIONS)


def permissions_for(roles: list[str] | tuple[str, ...]) -> set[Perm]:
    perms: set[Perm] = set()
    for r in roles:
        perms |= ROLE_PERMISSIONS.get(r, set())
    return perms
