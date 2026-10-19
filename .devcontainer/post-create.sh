#!/usr/bin/env bash
# Codespaces / Dev Container first-time setup.
set -euo pipefail
sudo apt-get update -qq
sudo apt-get install -y -qq postgresql-client redis-server >/dev/null
printf 'Waiting for PostgreSQL'
for _ in $(seq 1 60); do pg_isready -q -h localhost -p 5432 && break; printf '.'; sleep 1; done
echo
PSQL_SUPER="postgresql://postgres:postgres@localhost:5432/postgres" DB_HOST=localhost PYTHON=python3 \
  bash scripts/dev-setup.sh
