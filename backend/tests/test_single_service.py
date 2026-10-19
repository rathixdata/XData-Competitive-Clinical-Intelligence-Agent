"""Single-service deployment (render.yaml / root Dockerfile): first-run workspace, web app serving,
Postgres object store, in-process scheduler and hosted-database URL handling."""

from __future__ import annotations

import threading
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.core.config import Settings, get_settings
from app.db.session import get_engine, session_scope


@pytest.fixture
def bootstrap_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("XDATA_BOOTSTRAP_TENANT", "acme")
    monkeypatch.setenv("XDATA_BOOTSTRAP_TENANT_NAME", "Acme Bio")
    monkeypatch.setenv("XDATA_BOOTSTRAP_ADMIN_EMAIL", "Admin@Acme.example")
    monkeypatch.setenv("XDATA_BOOTSTRAP_ADMIN_PASSWORD", "Sup3r-Secret-Pass")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.parametrize("url", ["postgres://u:p@h:5432/d", "postgresql://u:p@h:5432/d",
                                 "postgresql+psycopg://u:p@h:5432/d"])
def test_hosted_database_urls_get_the_psycopg_driver(url: str) -> None:
    assert Settings(database_url=url).database_url == "postgresql+psycopg://u:p@h:5432/d"


def test_first_run_creates_a_real_workspace_once(bootstrap_env, client: TestClient) -> None:
    from app.bootstrap import bootstrap_workspace
    from app.models import Asset, ConnectorConfig, Landscape, Tenant, User

    with session_scope(bypass_rls=True) as db:
        created = bootstrap_workspace(db)
    assert created is not None
    with session_scope(bypass_rls=True) as db:
        assert bootstrap_workspace(db) is None  # idempotent
        tenant = db.scalar(select(Tenant).where(Tenant.slug == "acme"))
        assert tenant.name == "Acme Bio"
        user = db.scalar(select(User).where(User.tenant_id == tenant.id))
        assert user.email == "admin@acme.example" and "tenant_admin" in user.roles
        ls = db.scalar(select(Landscape).where(Landscape.tenant_id == tenant.id))
        assert ls.config["trial_queries"] and ls.config["pubmed_queries"]  # live searches, no fixtures
        assert db.scalar(select(Asset).where(Asset.tenant_id == tenant.id, Asset.is_internal.is_(True)))
        now = datetime.now(UTC)
        enabled = db.scalars(select(ConnectorConfig).where(ConnectorConfig.enabled.is_(True))).all()
        assert enabled and all(c.next_run_at <= now for c in enabled)  # first runs start right away
    r = client.post("/api/v1/auth/login", json={"tenant": "acme", "email": "admin@acme.example",
                                                "password": "Sup3r-Secret-Pass"})
    assert r.status_code == 200, r.text


def test_first_run_requires_admin_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.bootstrap import bootstrap_workspace

    monkeypatch.setenv("XDATA_BOOTSTRAP_TENANT", "acme")
    monkeypatch.setenv("XDATA_BOOTSTRAP_ADMIN_EMAIL", "admin@acme.example")
    monkeypatch.setenv("XDATA_BOOTSTRAP_ADMIN_PASSWORD", "short")
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="12"), session_scope(bypass_rls=True) as db:
            bootstrap_workspace(db)
    finally:
        get_settings.cache_clear()


def test_postgres_object_store_is_content_addressed_and_write_once() -> None:
    from app.storage.object_store import PostgresObjectStore

    store = PostgresObjectStore()
    key, digest = store.put_content_addressed("ctgov", b'{"a":1}', "application/json")
    assert store.put_content_addressed("ctgov", b'{"a":1}', "application/json") == (key, digest)
    assert store.get(key) == b'{"a":1}' and store.verify(key, digest)
    with pytest.raises(Exception, match="append-only"), get_engine().begin() as c:
        c.execute(text("UPDATE raw_objects SET data = 'x' WHERE key = :k"), {"k": key})
    with pytest.raises(FileNotFoundError):
        store.get("ctgov/00/missing")


def test_web_app_is_served_with_client_side_route_fallback(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><div id=root></div>")
    (tmp_path / "assets" / "app-123.js").write_text("console.log(1)")
    (tmp_path.parent / "secret.txt").write_text("nope")
    monkeypatch.setenv("XDATA_STATIC_DIR", str(tmp_path))
    get_settings.cache_clear()
    try:
        from app.main import create_app

        c = TestClient(create_app())
        for path in ("/", "/events/123", "/admin/users"):
            r = c.get(path)
            assert r.status_code == 200 and "id=root" in r.text and r.headers["cache-control"] == "no-cache"
        js = c.get("/assets/app-123.js")
        assert js.text == "console.log(1)" and "immutable" in js.headers["cache-control"]
        assert "nope" not in c.get("/../secret.txt").text
        api = c.get("/api/v1/does-not-exist")
        assert api.status_code == 404 and api.json()["error"]["code"] == "not_found"
        assert c.get("/healthz").json() == {"status": "ok"}
    finally:
        get_settings.cache_clear()


def test_inprocess_scheduler_runs_jobs_and_stops(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import scheduler

    ran = threading.Event()
    monkeypatch.setattr(scheduler, "_jobs", lambda: [("probe", 60, ran.set)])
    monkeypatch.setattr(scheduler, "_daily_jobs", lambda: [])
    scheduler.start(initial_delay=0)
    try:
        assert ran.wait(5)
    finally:
        scheduler.stop()
        scheduler._thread.join(10)
    assert not scheduler._thread.is_alive()


def test_check_now_runs_in_the_background_in_single_service_mode(bootstrap_env, monkeypatch: pytest.MonkeyPatch,
                                                                  client: TestClient) -> None:
    from app.bootstrap import bootstrap_workspace
    from app.workers import tasks

    with session_scope(bypass_rls=True) as db:
        bootstrap_workspace(db)
    monkeypatch.setenv("XDATA_INPROCESS_SCHEDULER", "true")
    get_settings.cache_clear()
    started, release = threading.Event(), threading.Event()

    def slow_run(args, kwargs, task_id=None):  # stands in for a multi-minute connector run
        started.set()
        release.wait(10)

    monkeypatch.setattr(tasks.run_connector_task, "apply", slow_run)
    token = client.post("/api/v1/auth/login", json={"tenant": "acme", "email": "admin@acme.example",
                                                    "password": "Sup3r-Secret-Pass"}).json()["access_token"]
    r = client.post("/api/v1/admin/connectors/ctgov/run", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 202 and r.json()["queued"] is True  # returned while the run is still going
    assert started.wait(5)
    release.set()
