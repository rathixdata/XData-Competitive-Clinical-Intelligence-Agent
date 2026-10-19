"""Run the complete XData CI Agent on one computer, with nothing else installed.

Uses an embedded PostgreSQL 16 + pgvector (the ``pgserver`` package) kept in a data folder, runs the
database migrations, creates your workspace on the first start, then serves the web app and API on
http://localhost and runs the live source schedule in the background. Stop it with Ctrl-C (or by
closing the Terminal window); your data stays in the data folder for the next start.

    python desktop/xdata_local.py            # normally started by "Start XData CI Agent.command"

Settings live in <home>/settings.env (created on first start, with your login and generated secrets).
Add XDATA_ANTHROPIC_API_KEY=... there to have Claude write the summaries and answers.
"""

from __future__ import annotations

import os
import secrets
import signal
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # repository / app folder
BACKEND = ROOT / "backend"
HOME = Path(os.environ.get("XDATA_HOME", Path.home() / "XData-CI-Agent")).expanduser()
DATA = HOME / "data"
SETTINGS = HOME / "settings.env"
LOGIN = HOME / "LOGIN.txt"
WORKSPACE = "my-company"


def say(msg: str) -> None:
    print(f"==> {msg}", flush=True)


def read_settings() -> dict[str, str]:
    out: dict[str, str] = {}
    if SETTINGS.exists():
        for line in SETTINGS.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def ask_email() -> str:
    """The admin sign-in email: from the installer (XDATA_SETUP_EMAIL), else asked here, else a placeholder."""
    email = os.environ.get("XDATA_SETUP_EMAIL", "").strip().lower()
    if not email and sys.stdin.isatty():
        email = input("Your email address (used to sign in): ").strip().lower()
    # Reserved domains such as .local or .example are refused by the sign-in form's email check.
    return email if "@" in email and "." in email.split("@")[-1] else "admin@xdata-ci-agent.com"


def first_settings() -> dict[str, str]:
    """Create settings.env with a login and generated secrets on the very first start."""
    password = "-".join(secrets.token_urlsafe(4) for _ in range(3))  # e.g. Xy3k-9QpA-mm2w (12+ characters)
    values = {
        "XDATA_BOOTSTRAP_TENANT": WORKSPACE,
        "XDATA_BOOTSTRAP_TENANT_NAME": "My Company",
        "XDATA_BOOTSTRAP_ADMIN_EMAIL": ask_email(),
        "XDATA_BOOTSTRAP_ADMIN_PASSWORD": password,
        "XDATA_JWT_SECRET": secrets.token_urlsafe(48),
        "XDATA_FIELD_ENCRYPTION_KEY": secrets.token_urlsafe(32),
        "XDATA_WEBHOOK_SIGNING_SECRET": secrets.token_urlsafe(32),
    }
    SETTINGS.write_text(
        "# XData CI Agent settings. Restart the app after changing this file.\n"
        "# Your login (the workspace and admin account are created on the first start):\n"
        + "".join(f"{k}={values[k]}\n" for k in ("XDATA_BOOTSTRAP_TENANT", "XDATA_BOOTSTRAP_TENANT_NAME",
                                                 "XDATA_BOOTSTRAP_ADMIN_EMAIL", "XDATA_BOOTSTRAP_ADMIN_PASSWORD"))
        + "\n# Optional: a Claude API key (https://console.anthropic.com) for AI-written summaries and answers.\n"
        "# XDATA_ANTHROPIC_API_KEY=sk-ant-...\n"
        "\n# Generated secrets - keep them, or saved sessions and stored credentials stop working.\n"
        + "".join(f"{k}={values[k]}\n" for k in ("XDATA_JWT_SECRET", "XDATA_FIELD_ENCRYPTION_KEY",
                                                 "XDATA_WEBHOOK_SIGNING_SECRET"))
    )
    SETTINGS.chmod(0o600)
    return values


def start_database():  # type: ignore[no-untyped-def]
    import pgserver
    import psycopg

    pgdata = DATA / "postgres"
    say("Starting the built-in database")
    # The launcher stops the server itself (stop_database), so a crashed earlier run can never block that.
    srv = pgserver.get_server(pgdata, cleanup_mode=None)
    with psycopg.connect(srv.get_uri("postgres"), autocommit=True) as c:
        if not c.execute("SELECT 1 FROM pg_roles WHERE rolname = 'xdata'").fetchone():
            # A normal (non-superuser) role, so row-level security applies to the app exactly as in production.
            c.execute("CREATE ROLE xdata LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS")
        if not c.execute("SELECT 1 FROM pg_database WHERE datname = 'xdata'").fetchone():
            c.execute("CREATE DATABASE xdata OWNER xdata")
    with psycopg.connect(srv.get_uri("xdata"), autocommit=True) as c:
        c.execute("CREATE EXTENSION IF NOT EXISTS vector")
        if c.execute("SELECT 1 FROM pg_available_extensions WHERE name = 'pg_trgm'").fetchone():
            c.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        c.execute("ALTER SCHEMA public OWNER TO xdata")
    host = psycopg.conninfo.conninfo_to_dict(srv.get_uri("xdata")).get("host")
    url = f"postgresql+psycopg://xdata@/xdata?host={host}" if host else "postgresql+psycopg://xdata@localhost/xdata"
    return srv, url


def stop_database() -> None:
    import subprocess

    from pgserver._commands import POSTGRES_BIN_PATH

    subprocess.run([str(POSTGRES_BIN_PATH / "pg_ctl"), "-D", str(DATA / "postgres"), "-m", "fast", "-w", "-t", "30",
                    "stop"], check=False, capture_output=True)


def free_port(start: int) -> int:
    for port in range(start, start + 50):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise SystemExit("no free port found")


def open_browser_when_ready(url: str) -> None:
    def wait() -> None:
        for _ in range(240):
            try:
                if urllib.request.urlopen(url + "/healthz", timeout=2).status == 200:
                    if os.environ.get("XDATA_NO_BROWSER") != "1":
                        webbrowser.open(url)
                    return
            except Exception:  # noqa: BLE001 - not up yet
                time.sleep(0.5)

    threading.Thread(target=wait, daemon=True).start()


def already_running() -> str | None:
    """Address of an instance that is already serving (started earlier and still open), if any."""
    try:
        port = int((DATA / "port").read_text().strip())
        url = f"http://localhost:{port}"
        if urllib.request.urlopen(url + "/healthz", timeout=2).status == 200:
            return url
    except Exception:  # noqa: BLE001 - no record, or nothing listening
        return None
    return None


def _exit_on_signal(signum, _frame):  # type: ignore[no-untyped-def]
    # Ctrl-C and shutdown: the web server stops gracefully first (it re-raises the signal when done), then
    # this runs the cleanup in main() instead of printing a traceback.
    raise SystemExit(0)


def _hangup(_signum, _frame):  # type: ignore[no-untyped-def]
    # Closing the Terminal window sends SIGHUP; treat it as a normal shutdown request.
    os.kill(os.getpid(), signal.SIGTERM)


def main() -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(exist_ok=True)
    running = already_running()
    if running:
        say(f"XData CI Agent is already running at {running}; opening it in your browser")
        if os.environ.get("XDATA_NO_BROWSER") != "1":
            webbrowser.open(running)
        return
    signal.signal(signal.SIGINT, _exit_on_signal)
    signal.signal(signal.SIGTERM, _exit_on_signal)
    if hasattr(signal, "SIGHUP"):
        signal.signal(signal.SIGHUP, _hangup)
    first_start = not SETTINGS.exists()
    if first_start:
        first_settings()
    cfg = read_settings()

    _srv, db_url = start_database()  # keep the handle for the life of the app
    port = int(os.environ.get("XDATA_PORT") or free_port(8765))
    (DATA / "port").write_text(str(port))
    base = f"http://localhost:{port}"
    env = {
        "XDATA_ENV": "production",
        "XDATA_DATABASE_URL": db_url,
        "XDATA_STATIC_DIR": str(ROOT / "frontend" / "dist"),
        "XDATA_INPROCESS_SCHEDULER": "true",
        "XDATA_CELERY_EAGER": "true",
        "XDATA_REDIS_URL": "redis://127.0.0.1:1/0",  # no Redis on a desktop: rate limits fall back to memory
        "XDATA_OBJECT_STORE_BACKEND": "local",
        "XDATA_OBJECT_STORE_LOCAL_PATH": str(DATA / "objects"),
        "XDATA_PUBLIC_BASE_URL": base,
        "XDATA_CORS_ORIGINS": f'["{base}"]',
        "XDATA_LOG_JSON": "false",
        "XDATA_LOG_LEVEL": "WARNING",
        "XDATA_EMBEDDING_PROVIDER": "hashing",
        **cfg,
    }
    env.setdefault("XDATA_LLM_PROVIDER", "anthropic" if cfg.get("XDATA_ANTHROPIC_API_KEY") else "offline")
    email = cfg.get("XDATA_BOOTSTRAP_ADMIN_EMAIL", "")
    env.setdefault("XDATA_NCBI_EMAIL", email)
    env.setdefault("XDATA_SEC_USER_AGENT", f"XData CI Agent {email}")
    os.environ.update(env)
    sys.path.insert(0, str(BACKEND))

    if not (ROOT / "frontend" / "dist" / "index.html").exists():
        raise SystemExit("The web app is not built (frontend/dist is missing). Run the installer again.")

    say("Preparing the database (first start takes about a minute)")
    from alembic import command
    from alembic.config import Config

    alembic_cfg = Config(str(BACKEND / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    command.upgrade(alembic_cfg, "head")

    from app.bootstrap import bootstrap_workspace
    from app.db.session import session_scope
    from app.pipeline.ingest import ensure_connector_configs

    with session_scope(bypass_rls=True) as db:
        ensure_connector_configs(db)
        created = bootstrap_workspace(db)
    if created:
        say("Created your workspace; live data from ClinicalTrials.gov, PubMed and the FDA starts arriving in a few minutes")

    login = (f"Address:                {base}\n"
             f"Organisation workspace: {cfg.get('XDATA_BOOTSTRAP_TENANT', WORKSPACE)}\n"
             f"Email:                  {email}\n"
             f"Password:               {cfg.get('XDATA_BOOTSTRAP_ADMIN_PASSWORD', '(see settings.env)')}\n")
    LOGIN.write_text("XData CI Agent - your sign-in details\n\n" + login +
                     f"\nSettings: {SETTINGS}\nData:     {DATA}\n")
    LOGIN.chmod(0o600)
    bar = "=" * 64
    print(f"\n{bar}\n XData CI Agent is running. Your browser opens automatically.\n\n{login}\n"
          f" These details are also saved in {LOGIN}\n Keep this window open while you use the app. "
          f"Press Ctrl-C to stop.\n{bar}\n", flush=True)

    import uvicorn

    open_browser_when_ready(base)
    try:
        uvicorn.run("app.main:app", host="127.0.0.1", port=port, log_level="warning")
    finally:
        say("Stopping the database")
        try:
            stop_database()
        except Exception as e:  # noqa: BLE001 - never leave a traceback as the last thing the user sees
            print(f"   (could not stop the database cleanly: {e}; the next start reuses it)", flush=True)
        say("Stopped. Your data is kept for the next start.")


if __name__ == "__main__":
    main()
