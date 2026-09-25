"""Engine / session management with tenant context propagated to Postgres RLS.

Every transaction runs ``set_config('app.current_tenant', <tenant>, true)`` so that
row-level-security policies (see alembic migration 0001) enforce tenant isolation in the
database itself, in addition to application-level filters (NFR-SEC-001, defence in depth).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


@lru_cache
def get_engine() -> Engine:
    s = get_settings()
    engine = create_engine(
        s.database_url,
        pool_size=s.db_pool_size,
        max_overflow=s.db_max_overflow,
        pool_pre_ping=True,
        future=True,
        connect_args={"options": f"-c statement_timeout={s.db_statement_timeout_ms}"},
    )
    return engine


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False, autoflush=False)


@event.listens_for(Session, "after_begin")
def _apply_tenant_context(session: Session, _transaction, connection) -> None:  # type: ignore[no-untyped-def]
    tenant = session.info.get("tenant_id")
    bypass = session.info.get("bypass_rls", False)
    connection.exec_driver_sql(
        "SELECT set_config('app.current_tenant', %(t)s, true), set_config('app.bypass_rls', %(b)s, true)",
        {"t": str(tenant) if tenant else "", "b": "on" if bypass else "off"},
    )


def new_session(tenant_id: uuid.UUID | None = None, *, bypass_rls: bool = False) -> Session:
    session = get_sessionmaker()()
    session.info["tenant_id"] = tenant_id
    session.info["bypass_rls"] = bypass_rls
    return session


@contextmanager
def session_scope(tenant_id: uuid.UUID | None = None, *, bypass_rls: bool = False) -> Iterator[Session]:
    """Transactional scope. Use ``bypass_rls=True`` only for system pipelines (connectors, workers)."""
    session = new_session(tenant_id, bypass_rls=bypass_rls)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def set_tenant(session: Session, tenant_id: uuid.UUID | None, *, bypass_rls: bool | None = None) -> None:
    """Switch tenant context; takes effect at the next transaction begin (and immediately if in one)."""
    session.info["tenant_id"] = tenant_id
    if bypass_rls is not None:
        session.info["bypass_rls"] = bypass_rls
    if session.in_transaction():
        session.connection().exec_driver_sql(
            "SELECT set_config('app.current_tenant', %(t)s, true), set_config('app.bypass_rls', %(b)s, true)",
            {"t": str(tenant_id) if tenant_id else "", "b": "on" if session.info.get("bypass_rls") else "off"},
        )
