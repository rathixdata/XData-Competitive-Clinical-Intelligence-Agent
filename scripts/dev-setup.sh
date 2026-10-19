#!/usr/bin/env bash
# One-time (idempotent) local setup WITHOUT Docker:
# database role + extensions, Python venv, migrations, demo data, frontend packages.
#
# Environment (all optional):
#   PSQL_SUPER   psql connection for a superuser   (default: "postgresql:///postgres" = local socket, current OS user)
#   DB_HOST      host the app uses for Postgres    (default: localhost)
#   DB_PORT      port                              (default: 5432)
#   PYTHON       python >= 3.11 interpreter        (default: first of python3.12 / python3.11 / python3)
#   PSQL         psql binary                       (default: psql on PATH)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PSQL_SUPER="${PSQL_SUPER:-postgresql:///postgres}"
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"
PSQL="${PSQL:-psql}"
say() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
die() { printf '\n\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

if [ -z "${PYTHON:-}" ]; then
  for p in python3.12 python3.11 python3; do
    if command -v "$p" >/dev/null 2>&1 && "$p" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
      PYTHON="$p"; break
    fi
  done
fi
[ -n "${PYTHON:-}" ] || die "Python 3.11+ not found."
command -v "$PSQL" >/dev/null 2>&1 || die "psql not found."
command -v npm >/dev/null 2>&1 || die "npm (Node.js) not found."

say "Checking PostgreSQL connection"
"$PSQL" "$PSQL_SUPER" -Atqc "select 1" >/dev/null || die "Cannot connect to PostgreSQL with: $PSQL_SUPER"
"$PSQL" "$PSQL_SUPER" -Atqc "select 1 from pg_available_extensions where name='vector'" | grep -q 1 \
  || die "The pgvector extension is not installed in this PostgreSQL."

say "Creating database role 'xdata' and database 'xdata' (non-superuser, so row-level security applies)"
"$PSQL" "$PSQL_SUPER" -v ON_ERROR_STOP=1 -q <<'SQL'
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'xdata') THEN
    CREATE ROLE xdata LOGIN PASSWORD 'xdata' NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
  END IF;
END $$;
SQL
if ! "$PSQL" "$PSQL_SUPER" -Atqc "select 1 from pg_database where datname='xdata'" | grep -q 1; then
  "$PSQL" "$PSQL_SUPER" -qc "CREATE DATABASE xdata OWNER xdata"
fi
XDATA_SUPER="$("$PYTHON" -c 'import sys,re; u=sys.argv[1]; print(re.sub(r"/[^/?]*(\?|$)", r"/xdata\1", u, count=1) if re.search(r"//[^/]*/", u) else u)' "$PSQL_SUPER")"
"$PSQL" "$XDATA_SUPER" -v ON_ERROR_STOP=1 -qc "CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pg_trgm; ALTER SCHEMA public OWNER TO xdata;"

say "Creating Python environment (.venv) and installing the backend"
[ -x .venv/bin/python ] || "$PYTHON" -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -e "backend[dev]"

ENV_FILE="$ROOT/.data/dev.env"
mkdir -p "$ROOT/.data"
cat > "$ENV_FILE" <<ENV
export XDATA_ENV=development
export XDATA_DATABASE_URL=postgresql+psycopg://xdata:xdata@${DB_HOST}:${DB_PORT}/xdata
export XDATA_REDIS_URL=redis://localhost:6379/0
export XDATA_OBJECT_STORE_BACKEND=local
export XDATA_OBJECT_STORE_LOCAL_PATH=$ROOT/.data/objects
export XDATA_LLM_PROVIDER=\${XDATA_LLM_PROVIDER:-offline}
export XDATA_EMBEDDING_PROVIDER=\${XDATA_EMBEDDING_PROVIDER:-hashing}
export XDATA_LOG_JSON=false
export XDATA_LOG_LEVEL=WARNING
export XDATA_CORS_ORIGINS='["http://localhost:5173"]'
ENV
# shellcheck disable=SC1090
source "$ENV_FILE"

say "Applying database migrations"
(cd backend && ../.venv/bin/alembic upgrade head)

if "$PSQL" "$XDATA_SUPER" -Atqc "select 1 from tenants where slug='demo-oncology'" | grep -q 1; then
  say "Demo data already loaded (skipping)"
else
  say "Loading demo data through the real ingestion pipeline (about 10 seconds)"
  (cd backend && ../.venv/bin/python -m app.cli seed-demo >/dev/null)
fi

say "Installing frontend packages"
(cd frontend && npm ci --no-audit --no-fund --loglevel=error)

say "Setup complete. Start the app with: scripts/dev-start.sh"
