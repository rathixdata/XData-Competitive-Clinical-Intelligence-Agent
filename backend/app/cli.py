"""Operational CLI: ``python -m app.cli <command>``."""

from __future__ import annotations

import argparse
import getpass
import json
import sys

from sqlalchemy import select

from app.core.config import get_settings
from app.core.crypto import hash_password
from app.core.logging import configure_logging
from app.db.session import session_scope


def cmd_bootstrap(a: argparse.Namespace) -> None:
    """Create a tenant and its first administrator (production onboarding)."""
    from app.models import Tenant, User
    from app.services import audit

    pw = a.password or getpass.getpass("Admin password (min 12 chars, blank for SSO-only): ")
    if pw and len(pw) < 12:
        sys.exit("password must be at least 12 characters")
    with session_scope(bypass_rls=True) as db:
        t = db.scalar(select(Tenant).where(Tenant.slug == a.tenant))
        if t is None:
            t = Tenant(name=a.name or a.tenant, slug=a.tenant, deployment_mode=a.mode, settings={})
            db.add(t)
            db.flush()
        u = db.scalar(select(User).where(User.tenant_id == t.id, User.email == a.admin_email.lower()))
        if u is None:
            u = User(tenant_id=t.id, email=a.admin_email.lower(), display_name="Administrator", roles=["tenant_admin"],
                     password_hash=hash_password(pw) if pw else None, external_subject=a.sso_subject)
            db.add(u)
        db.flush()
        audit.record(db, action="tenant.bootstrap", resource_type="tenant", resource_id=t.id, tenant_id=t.id,
                     actor_id="cli", actor_type="system", after={"slug": t.slug, "admin": u.email})
        print(json.dumps({"tenant_id": str(t.id), "admin_user_id": str(u.id)}))


def cmd_seed_demo(a: argparse.Namespace) -> None:
    from app.seed.demo import seed_demo

    print(json.dumps(seed_demo(with_pipeline=not a.no_pipeline, use_llm=a.use_llm), default=str, indent=2))


def cmd_run_connector(a: argparse.Namespace) -> None:
    from app.pipeline.ingest import run_connector

    print(run_connector(a.key, trigger="manual", requested_by="cli"))


def cmd_process_changes(a: argparse.Namespace) -> None:
    from app.pipeline.intelligence import process_pending_changes

    print(json.dumps(process_pending_changes(use_llm=not a.no_llm)))


def cmd_reembed(_a: argparse.Namespace) -> None:
    from app.rag.indexer import reembed_all

    with session_scope(bypass_rls=True) as db:
        print(f"re-embedded {reembed_all(db)} chunks")


def cmd_verify_audit(a: argparse.Namespace) -> None:
    import uuid

    from app.services.audit import verify_chain

    with session_scope(bypass_rls=True) as db:
        print(json.dumps(verify_chain(db, uuid.UUID(a.tenant_id) if a.tenant_id else None)))


def cmd_check_config(_a: argparse.Namespace) -> None:
    s = get_settings()
    print(json.dumps({"env": s.env, "llm_provider": s.llm_provider, "llm_model": s.llm_model,
                      "embedding_provider": s.embedding_provider, "object_store": s.object_store_backend,
                      "oidc": bool(s.oidc_jwks_url)}))


def main(argv: list[str] | None = None) -> None:
    configure_logging()
    p = argparse.ArgumentParser(prog="xdata")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("bootstrap")
    b.add_argument("--tenant", required=True)
    b.add_argument("--name")
    b.add_argument("--admin-email", required=True)
    b.add_argument("--password")
    b.add_argument("--sso-subject")
    b.add_argument("--mode", default="multi_tenant", choices=["multi_tenant", "dedicated"])
    b.set_defaults(fn=cmd_bootstrap)
    s = sub.add_parser("seed-demo")
    s.add_argument("--no-pipeline", action="store_true")
    s.add_argument("--use-llm", action="store_true")
    s.set_defaults(fn=cmd_seed_demo)
    r = sub.add_parser("run-connector")
    r.add_argument("key")
    r.set_defaults(fn=cmd_run_connector)
    pc = sub.add_parser("process-changes")
    pc.add_argument("--no-llm", action="store_true")
    pc.set_defaults(fn=cmd_process_changes)
    sub.add_parser("reembed").set_defaults(fn=cmd_reembed)
    v = sub.add_parser("verify-audit")
    v.add_argument("--tenant-id")
    v.set_defaults(fn=cmd_verify_audit)
    sub.add_parser("check-config").set_defaults(fn=cmd_check_config)
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
