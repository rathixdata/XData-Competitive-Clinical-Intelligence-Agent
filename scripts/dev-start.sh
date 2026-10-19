#!/usr/bin/env bash
# Start the API (port 8000) and web app (port 5173) without Docker. Run scripts/dev-setup.sh first.
#   scripts/dev-start.sh               foreground; Ctrl-C stops both
#   scripts/dev-start.sh --background  detach (logs in .data/logs); stop with scripts/dev-stop.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
[ -f .data/dev.env ] || { echo "Run scripts/dev-setup.sh first."; exit 1; }
# shellcheck disable=SC1091
source .data/dev.env
mkdir -p .data/logs

cd "$ROOT/backend"
nohup "$ROOT/.venv/bin/uvicorn" app.main:app --host 127.0.0.1 --port 8000 > "$ROOT/.data/logs/api.log" 2>&1 &
echo $! > "$ROOT/.data/api.pid"
cd "$ROOT"
printf 'Starting API'
for _ in $(seq 1 60); do
  if curl -sf http://127.0.0.1:8000/healthz >/dev/null 2>&1; then echo " ok"; break; fi
  printf '.'; sleep 1
done
curl -sf http://127.0.0.1:8000/healthz >/dev/null || { echo; echo "API failed to start; see .data/logs/api.log:"; tail -30 .data/logs/api.log; exit 1; }

cat <<MSG

  XData CI Agent is starting.
  Open:      http://localhost:5173
  Tenant:    demo-oncology
  Email:     analyst@demo.example
  Password:  ChangeMe-Demo-2026!
  API docs:  http://localhost:8000/api/v1/docs

MSG

if [ "${1:-}" = "--background" ]; then
  cd "$ROOT/frontend"
  nohup "$ROOT/frontend/node_modules/.bin/vite" --host 0.0.0.0 > "$ROOT/.data/logs/web.log" 2>&1 &
  echo $! > "$ROOT/.data/web.pid"
  echo "Running in background. Logs: .data/logs/  Stop: scripts/dev-stop.sh"
  exit 0
fi
trap 'kill "$(cat "$ROOT/.data/api.pid")" 2>/dev/null || true; rm -f "$ROOT/.data/api.pid"; echo; echo "Stopped."' EXIT
(command -v open >/dev/null 2>&1 && sleep 3 && open http://localhost:5173) >/dev/null 2>&1 &
cd "$ROOT/frontend" && "$ROOT/frontend/node_modules/.bin/vite"
