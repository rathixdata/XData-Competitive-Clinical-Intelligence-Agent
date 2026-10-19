#!/usr/bin/env bash
# One command to install everything natively on macOS (no Docker) and run the app.
#   bash scripts/run-mac.sh
# Uses Homebrew: PostgreSQL 17 + pgvector, Redis, Python 3.12, Node.js.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
say() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
die() { printf '\n\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(uname -s)" = "Darwin" ] || die "This script is for macOS. On Linux use scripts/dev-setup.sh."

if ! command -v brew >/dev/null 2>&1; then
  for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do [ -x "$b" ] && eval "$("$b" shellenv)"; done
fi
if ! command -v brew >/dev/null 2>&1; then
  cat <<'MSG'

Homebrew is not installed. Install it by pasting this into Terminal, then run this script again:

  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

MSG
  exit 1
fi

say "Installing PostgreSQL 17, pgvector, Redis, Python 3.12 and Node.js with Homebrew (first time: a few minutes)"
brew install postgresql@17 pgvector redis python@3.12 node

PG_PREFIX="$(brew --prefix postgresql@17)"
export PATH="$PG_PREFIX/bin:$(brew --prefix python@3.12)/bin:$PATH"

if ! ls "$PG_PREFIX"/share/postgresql@17/extension/vector.control >/dev/null 2>&1 \
   && ! ls "$(pg_config --sharedir)"/extension/vector.control >/dev/null 2>&1; then
  say "pgvector not found for PostgreSQL 17; building it from source"
  TMP="$(mktemp -d)"
  git clone --quiet --branch v0.8.0 --depth 1 https://github.com/pgvector/pgvector.git "$TMP/pgvector"
  (cd "$TMP/pgvector" && make -s PG_CONFIG="$PG_PREFIX/bin/pg_config" && make -s install PG_CONFIG="$PG_PREFIX/bin/pg_config")
fi

say "Starting PostgreSQL and Redis as background services"
brew services start postgresql@17 >/dev/null
brew services start redis >/dev/null
printf 'Waiting for PostgreSQL'
for _ in $(seq 1 30); do pg_isready -q -h localhost -p 5432 && break; printf '.'; sleep 1; done
echo
pg_isready -q -h localhost -p 5432 || die "PostgreSQL did not start. Try: brew services restart postgresql@17"

PSQL="$PG_PREFIX/bin/psql" PSQL_SUPER="postgresql://$(whoami)@localhost:5432/postgres" \
  PYTHON="$(brew --prefix python@3.12)/bin/python3.12" bash "$ROOT/scripts/dev-setup.sh"

bash "$ROOT/scripts/dev-start.sh"
