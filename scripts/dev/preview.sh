#!/usr/bin/env bash
# Developer helper (not for end users): start an isolated backend + Vite dev server pair.
#   scripts/dev/preview.sh <base_port> [--demo]
# Backend on <base_port>, frontend on <base_port+1>, data in /tmp/claude-0/preview-<base_port>.
# Prints the frontend URL. Stop with: scripts/dev/preview.sh <base_port> --stop
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BASE="${1:?base port}"; shift || true
FRONT=$((BASE+1))
DATA="/tmp/claude-0/preview-$BASE"
if [[ "${1:-}" == "--stop" ]]; then
  pkill -f "paladex serve --no-browser --port $BASE" || true
  pkill -f "vite --port $FRONT" || true
  exit 0
fi
mkdir -p "$DATA"
cd "$ROOT/backend"
source .venv/bin/activate
export PALADEX_DATA_DIR="$DATA" PALADEX_SCHEDULER_ENABLED=false
python -m paladex init-db >/dev/null
if [[ "${1:-}" == "--demo" ]]; then python -m paladex seed-demo >/dev/null; fi
nohup python -m paladex serve --no-browser --port "$BASE" > "$DATA/backend.log" 2>&1 &
cd "$ROOT/frontend"
PALADEX_API="http://127.0.0.1:$BASE" nohup npx vite --port "$FRONT" --strictPort > "$DATA/vite.log" 2>&1 &
for i in $(seq 1 30); do
  if curl -s "http://127.0.0.1:$FRONT" >/dev/null && curl -s "http://127.0.0.1:$BASE/api/health" >/dev/null; then break; fi
  sleep 1
done
echo "http://127.0.0.1:$FRONT"
