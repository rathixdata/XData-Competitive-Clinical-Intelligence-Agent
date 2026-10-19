#!/usr/bin/env bash
# Stop servers started with scripts/dev-start.sh --background.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
for f in api web; do
  [ -f "$ROOT/.data/$f.pid" ] && kill "$(cat "$ROOT/.data/$f.pid")" 2>/dev/null && echo "stopped $f"
  rm -f "$ROOT/.data/$f.pid"
done
exit 0
