"""Security tests: authentication, RBAC, tenant isolation (API + RLS), API keys, idempotency, audit
immutability and hash chain (NFR-SEC-001/002/003, NFR-AUD-001, Section 11)."""

from __future__ import annotations

import pytest
from sqlalchemy import select, text

from app.db.session import session_scope
from app.models import Asset, AuditLog, IntelligenceEvent, Landscape
from tests.conftest import login


def test_unauthenticated_and_bad_tokens_rejected(client, seeded):
    assert client.get("/api/v1/events").status_code == 401
    assert client.get("/api/v1/events", headers={"Authorization": "Bearer nope"}).status_code == 401
    r = client.post("/api/v1/auth/login", json={"tenant": "demo-oncology", "email": "analyst@demo.example",
                                                 "password": "wrong-password"})
    assert r.status_code == 401


def test_rbac_enforced_server_side(client, demo_pipeline):
    exec_h = login(client, "cso@demo.example")
    auditor_h = login(client, "auditor@demo.example")
    ev = client.get("/api/v1/events", headers=exec_h).json()["items"][0]
    edit = {"statements": [], "reason": "try"}
    assert client.put(f"/api/v1/events/{ev['id']}/narrative", json=edit, headers=exec_h).status_code == 403
    assert client.get("/api/v1/admin/users", headers=exec_h).status_code == 403
    assert client.get("/api/v1/audit", headers=exec_h).status_code == 403
    assert client.get("/api/v1/audit", headers=auditor_h).status_code == 200
    assert client.post("/api/v1/ask", json={"question": "hello there"}, headers=auditor_h).status_code == 403
    assert client.patch("/api/v1/admin/connectors/ctgov", json={"enabled": False},
                        headers=login(client, "admin@demo.example")).status_code == 403  # platform-only


def test_cross_tenant_api_isolation(client, demo_pipeline, second_tenant):
    a = login(client)
    b = login(client, "analyst@other.example", "other-pharma")
    ev_id = client.get("/api/v1/events", headers=a).json()["items"][0]["id"]
    assert client.get(f"/api/v1/events/{ev_id}", headers=b).status_code == 404
    assert client.get("/api/v1/events", headers=b).json()["total"] == 0
    xd = str(demo_pipeline["xd101"])
    assert client.get(f"/api/v1/assets/{xd}", headers=b).status_code == 404
    names = [x["canonical_name"] for x in client.get("/api/v1/assets?limit=500", headers=b).json()["items"]]
    assert "XD-101" not in names and "OP-900" in names
    ls = client.get(f"/api/v1/landscapes/{demo_pipeline['landscape_id']}", headers=b)
    assert ls.status_code == 404
    hits = client.get("/api/v1/entities/search?q=XD-101", headers=b).json()
    assert not any(h["name"] == "XD-101" for h in hits)


def test_rls_blocks_cross_tenant_rows_at_database_level(demo_pipeline, second_tenant):
    b = second_tenant["tenant_id"]
    with session_scope(b) as db:
        # no application filter at all - the database itself must hide tenant A's rows
        assert db.scalars(select(IntelligenceEvent)).all() == []
        assert db.get(Asset, demo_pipeline["xd101"]) is None
        assert all(ls.tenant_id == b for ls in db.scalars(select(Landscape)).all())
        assert db.execute(text("SELECT count(*) FROM claims")).scalar() == 0
    with pytest.raises(Exception), session_scope(b) as db:  # noqa: B017 - WITH CHECK rejects foreign writes
        db.add(Landscape(tenant_id=demo_pipeline["tenant_id"], name="evil", config={}))
        db.flush()


def test_api_keys_narrow_roles_and_can_be_revoked(client, seeded):
    admin = login(client, "admin@demo.example")
    r = client.post("/api/v1/auth/api-keys", json={"name": "ci", "roles": ["tenant_admin"]}, headers=admin)
    assert r.status_code == 201
    key_h = {"Authorization": f"Bearer {r.json()['key']}"}
    assert client.get("/api/v1/auth/me", headers=key_h).json()["auth_method"] == "api_key"
    analyst = login(client)
    bad = client.post("/api/v1/auth/api-keys", json={"name": "x", "roles": ["tenant_admin"]}, headers=analyst)
    assert bad.status_code == 422  # cannot mint roles you don't hold
    assert client.delete(f"/api/v1/auth/api-keys/{r.json()['id']}", headers=admin).status_code == 204
    assert client.get("/api/v1/auth/me", headers=key_h).status_code == 401


def test_idempotent_mutation(client, seeded):
    h = {**login(client), "Idempotency-Key": "create-ls-1"}
    body = {"name": "Idem landscape", "disease": "NSCLC"}
    r1 = client.post("/api/v1/landscapes", json=body, headers=h)
    r2 = client.post("/api/v1/landscapes", json=body, headers=h)
    assert r1.status_code == 201 and r2.json()["id"] == r1.json()["id"]
    r3 = client.post("/api/v1/landscapes", json={**body, "name": "Different"}, headers=h)
    assert r3.status_code == 409


def test_audit_log_is_append_only_and_hash_chained(client, demo_pipeline):
    h = login(client, "admin@demo.example")
    client.post("/api/v1/landscapes", json={"name": "Audited"}, headers=h)
    tid = demo_pipeline["tenant_id"]
    with pytest.raises(Exception), session_scope(tid) as db:  # noqa: B017
        row = db.scalar(select(AuditLog).where(AuditLog.tenant_id == tid).limit(1))
        row.reason = "tampered"
        db.flush()
    with session_scope(tid) as db:  # RLS exposes no DELETE policy: nothing is deletable by the app role
        assert db.execute(text("DELETE FROM audit_log")).rowcount == 0
    with session_scope(bypass_rls=True) as db:  # no UPDATE/DELETE policy even for system sessions;
        assert db.execute(text("DELETE FROM audit_log")).rowcount == 0  # the trigger backstops BYPASSRLS roles
    with session_scope(bypass_rls=True) as db:
        trg = db.execute(text("SELECT tgname FROM pg_trigger WHERE tgname = 'audit_log_immutable'")).scalar()
        assert trg == "audit_log_immutable"
    v = client.get("/api/v1/audit/verify", headers=login(client, "auditor@demo.example")).json()
    assert v["valid"] and v["checked"] > 0
    csv_ = client.get("/api/v1/audit/export?format=csv", headers=login(client, "auditor@demo.example"))
    assert csv_.status_code == 200 and "landscape.create" in csv_.text


def test_secrets_not_logged():
    from app.core.logging import redact_processor

    out = redact_processor(None, "info", {"event": "x", "authorization": "Bearer abc.def",
                                           "msg": "calling with Bearer eyJhbGciOi.xyz", "nested": {"api_key": "k"}})
    assert out["authorization"] == "[REDACTED]" and "eyJ" not in out["msg"] and out["nested"]["api_key"] == "[REDACTED]"


def test_alert_destinations_encrypted_at_rest(client, seeded):
    h = login(client)
    r = client.post("/api/v1/alerts/policies", json={"name": "slack", "channels": ["slack"],
                                                     "destinations": {"slack_webhook": "https://hooks.slack.com/services/T/B/SECRET"}},
                    headers=h)
    assert r.status_code == 201 and r.json()["destinations"]["slack_webhook"] == "configured"
    with session_scope(bypass_rls=True) as db:
        raw = db.execute(text("SELECT destinations_encrypted FROM alert_policies")).scalar()
        assert "SECRET" not in raw and "hooks.slack.com" not in raw
