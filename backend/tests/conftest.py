"""Test harness.

Tests run against a real PostgreSQL + pgvector database (``XDATA_DATABASE_URL``, default the local
``xdata_test``) as the NON-superuser application role, so row-level security is genuinely exercised.
LLM = offline deterministic provider unless a test injects a fake client; embeddings = hashing.
"""

from __future__ import annotations

import os
import tempfile

os.environ.setdefault("XDATA_ENV", "test")
os.environ.setdefault("XDATA_DATABASE_URL", "postgresql+psycopg://xdata:xdata@127.0.0.1:5432/xdata_test")
os.environ.setdefault("XDATA_REDIS_URL", "redis://127.0.0.1:6379/15")
os.environ["XDATA_LLM_PROVIDER"] = "offline"
os.environ["XDATA_EMBEDDING_PROVIDER"] = "hashing"
os.environ["XDATA_OBJECT_STORE_BACKEND"] = "local"
os.environ["XDATA_OBJECT_STORE_LOCAL_PATH"] = tempfile.mkdtemp(prefix="xdata-test-objects-")
os.environ["XDATA_CELERY_EAGER"] = "true"
os.environ["XDATA_LOG_JSON"] = "false"
os.environ["XDATA_LOG_LEVEL"] = "WARNING"
os.environ["XDATA_API_RATE_LIMIT_PER_MINUTE"] = "100000"
os.environ["XDATA_ASK_RATE_LIMIT_PER_MINUTE"] = "100000"
os.environ["XDATA_LOGIN_RATE_LIMIT_PER_MINUTE"] = "100000"

import uuid  # noqa: E402
from collections.abc import Iterator  # noqa: E402
from typing import Any  # noqa: E402

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.db.base import Base  # noqa: E402
from app.db.session import get_engine, session_scope  # noqa: E402

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO_PASSWORD = "ChangeMe-Demo-2026!"


@pytest.fixture(scope="session", autouse=True)
def _migrated() -> None:
    cfg = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND_DIR, "alembic"))
    command.upgrade(cfg, "head")
    with get_engine().connect() as c:
        is_super = c.execute(text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")).scalar()
    assert not is_super, "tests must run as a non-superuser role so RLS is enforced"


def truncate_all() -> None:
    import app.models  # noqa: F401

    names = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with get_engine().begin() as c:
        c.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
    from app.api.deps import limiter

    limiter._local.clear()
    if limiter._r() is not None:
        limiter._r().flushdb()


@pytest.fixture(autouse=True)
def _clean_db() -> Iterator[None]:
    truncate_all()
    yield


@pytest.fixture
def seeded() -> dict[str, Any]:
    from app.pipeline.ingest import ensure_connector_configs
    from app.seed.demo import seed_reference_data, seed_tenant

    with session_scope(bypass_rls=True) as db:
        ensure_connector_configs(db)
        ids = seed_reference_data(db)
        info = seed_tenant(db, ids)
    return {"ids": ids, **info}


@pytest.fixture
def second_tenant(seeded: dict[str, Any]) -> dict[str, Any]:
    """An unrelated tenant with its own private asset and landscape (isolation tests)."""
    from app.core.crypto import hash_password
    from app.models import Tenant, User
    from app.services.landscapes import create_internal_asset, create_landscape, set_members

    with session_scope(bypass_rls=True) as db:
        t = Tenant(name="Other Pharma", slug="other-pharma", settings={})
        db.add(t)
        db.flush()
        u = User(tenant_id=t.id, email="analyst@other.example", display_name="Other", roles=["ci_analyst"],
                 password_hash=hash_password(DEMO_PASSWORD))
        db.add(u)
        db.flush()
        a = create_internal_asset(db, t.id, str(u.id), {"name": "OP-900", "aliases": ["OP900"],
                                                         "profile": {"targets": ["Target-X"],
                                                                     "indications": ["Non-small cell lung cancer"],
                                                                     "line_of_therapy": "2L+"}})
        ls = create_landscape(db, t.id, str(u.id), {"name": "Other NSCLC", "disease": "Non-small cell lung cancer"})
        set_members(db, ls, str(u.id), [{"entity_type": "asset", "entity_id": a.id, "role": "customer"},
                                        {"entity_type": "asset", "entity_id": seeded["ids"]["asset:CA-201"],
                                         "role": "competitor"}])
        return {"tenant_id": t.id, "user_id": u.id, "asset_id": a.id, "landscape_id": ls.id}


@pytest.fixture
def client() -> TestClient:
    from app.main import app

    return TestClient(app)


def login(client: TestClient, email: str = "analyst@demo.example", tenant: str = "demo-oncology") -> dict[str, str]:
    r = client.post("/api/v1/auth/login", json={"tenant": tenant, "email": email, "password": DEMO_PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def auth(client: TestClient, seeded: dict[str, Any]):  # type: ignore[no-untyped-def]
    def _auth(email: str = "analyst@demo.example", tenant: str = "demo-oncology") -> dict[str, str]:
        return login(client, email, tenant)

    return _auth


@pytest.fixture
def demo_pipeline(seeded: dict[str, Any]) -> dict[str, Any]:
    from app.seed.demo import run_demo_pipeline

    return {**seeded, "pipeline": run_demo_pipeline(use_llm=False)}


def uid() -> str:
    return str(uuid.uuid4())
