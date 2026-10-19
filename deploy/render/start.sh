#!/bin/sh
# Container entrypoint for the all-in-one image: migrate, create the first workspace, serve.
set -eu

# Use Claude when an API key is provided, otherwise the deterministic evidence-only mode.
if [ -z "${XDATA_LLM_PROVIDER:-}" ]; then
  if [ -n "${XDATA_ANTHROPIC_API_KEY:-}" ]; then export XDATA_LLM_PROVIDER=anthropic; else export XDATA_LLM_PROVIDER=offline; fi
fi
# Links in alert emails point at this service (Render sets RENDER_EXTERNAL_URL).
if [ -z "${XDATA_PUBLIC_BASE_URL:-}" ] && [ -n "${RENDER_EXTERNAL_URL:-}" ]; then
  export XDATA_PUBLIC_BASE_URL="$RENDER_EXTERNAL_URL"
fi

# NCBI and SEC ask API clients to identify themselves with a contact address.
if [ -n "${XDATA_BOOTSTRAP_ADMIN_EMAIL:-}" ]; then
  : "${XDATA_NCBI_EMAIL:=$XDATA_BOOTSTRAP_ADMIN_EMAIL}"
  : "${XDATA_SEC_USER_AGENT:=XData CI Agent $XDATA_BOOTSTRAP_ADMIN_EMAIL}"
  export XDATA_NCBI_EMAIL XDATA_SEC_USER_AGENT
fi

echo "==> Waiting for the database"
python - <<'PY'
import sys, time
from sqlalchemy import create_engine, text
from app.core.config import get_settings
url = get_settings().database_url
for i in range(60):
    try:
        with create_engine(url).connect() as c:
            c.execute(text("SELECT 1"))
        sys.exit(0)
    except Exception as e:  # noqa: BLE001
        print(f"   database not ready yet ({type(e).__name__}); retrying", flush=True)
        time.sleep(2)
sys.exit("database never became reachable")
PY

echo "==> Applying database migrations"
alembic upgrade head

echo "==> Creating the first workspace (only on the very first start)"
python -m app.cli first-run

echo "==> Starting the web app and API on port ${PORT}"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT}" --workers "${WEB_CONCURRENCY:-1}" \
  --proxy-headers --forwarded-allow-ips='*' --no-server-header
