#!/usr/bin/env bash
# Paladex read-only online copy: builds the static site the owner opens on the phone.
#
#   scripts/mirror/build.sh <database.sqlite3> <output-dir>
#
#   1. copies the database (read-only, one consistent snapshot) and removes everything private
#      from the COPY (prepare_db.py): supplier quotes, alerts, unknown tables, demo rows, ...
#   2. builds the interface twice from the same sources: the normal build (driven by the crawler)
#      and the read-only build (published); frontend/dist is never touched
#   3. starts the real backend on the copy, on a free local port, scheduler and starter import off
#   4. drives the normal interface through every market page and records each answer (crawl.mjs)
#   5. assembles the site: read-only build + answers + manifest + Netlify rules (no indexing,
#      no stale caching, SPA fallback)
#   6. refuses to finish if any secret (API key, token, password) appears in the site
#
# Environment (all optional):
#   PALADEX_PYTHON       Python with the backend requirements (default backend/.venv/bin/python, else python3)
#   MIRROR_CONCURRENCY   browser tabs crawling in parallel (default 4)
#   MIRROR_MAX_FILE_MB   answers larger than this are left out, except the default view of a page (default 8)
#   MIRROR_VERIFY=1      afterwards, open the finished copy in a browser and count views it cannot answer
#   MIRROR_KEEP_WORK=1   keep the temporary work directory (logs, database copy)
set -euo pipefail

if [[ $# -ne 2 ]]; then
  sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'
  exit 2
fi
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DB="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
OUT="$(mkdir -p "$(dirname "$2")" && cd "$(dirname "$2")" && pwd)/$(basename "$2")"
case "$OUT/" in
  "$ROOT/"|"$ROOT/frontend/"*|"$ROOT/backend/"*|"$ROOT/data/"*|/) echo "Refusing to write the copy into $OUT" >&2; exit 2 ;;
esac
[[ -f "$DB" ]] || { echo "Database not found: $DB" >&2; exit 2; }

PY="${PALADEX_PYTHON:-}"
if [[ -z "$PY" ]]; then
  if [[ -x "$ROOT/backend/.venv/bin/python" ]]; then PY="$ROOT/backend/.venv/bin/python"; else PY="python3"; fi
fi
WORK="$(mktemp -d "${TMPDIR:-/tmp}/paladex-mirror.XXXXXX")"
BACKEND_PID=""
SERVE_PID=""
cleanup() {
  [[ -n "$BACKEND_PID" ]] && kill "$BACKEND_PID" 2>/dev/null && wait "$BACKEND_PID" 2>/dev/null || true
  [[ -n "$SERVE_PID" ]] && kill "$SERVE_PID" 2>/dev/null && wait "$SERVE_PID" 2>/dev/null || true
  if [[ "${MIRROR_KEEP_WORK:-}" == "1" ]]; then echo "Work directory kept: $WORK"; else rm -rf "$WORK"; fi
}
trap cleanup EXIT

T_START=$SECONDS
T_STEP=$SECONDS
TIMINGS=""
step() {
  if [[ -n "${STEP_NAME:-}" ]]; then TIMINGS+="  $(printf '%-34s %4d s' "$STEP_NAME" $((SECONDS - T_STEP)))"$'\n'; fi
  STEP_NAME="$1"; T_STEP=$SECONDS
  [[ -n "$1" ]] && echo "== $1"
  return 0
}
free_port() { "$PY" -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])'; }

step "1/6 private-data-free database copy"
"$PY" "$ROOT/scripts/mirror/prepare_db.py" "$DB" "$WORK/data/paladex.sqlite3" | tee "$WORK/prepare.json"

step "2/6 interface builds (normal + read-only)"
cd "$ROOT/frontend"
[[ -d node_modules ]] || npm ci --no-audit --no-fund
npx vite build --outDir "$WORK/normal-dist" --emptyOutDir --logLevel warn
VITE_PALADEX_MIRROR=1 npx vite build --outDir "$WORK/site" --emptyOutDir --logLevel warn
cd "$ROOT"

step "3/6 backend on the copy"
PORT="$(free_port)"
(
  cd "$ROOT/backend"
  # Same configuration as the collection (so key status is reported truthfully); the backend
  # never returns key values, and step 6 checks it.
  exec env PALADEX_DATA_DIR="$WORK/data" PALADEX_SCHEDULER_ENABLED=false PALADEX_STARTER_DATA_ENABLED=false \
    PALADEX_FRONTEND_DIST="$WORK/normal-dist" "$PY" -m paladex serve --no-browser --port "$PORT"
) > "$WORK/backend.log" 2>&1 &
BACKEND_PID=$!
for _ in $(seq 1 180); do
  if curl -sf "http://127.0.0.1:$PORT/api/health" > /dev/null 2>&1; then break; fi
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then echo "The backend did not start:" >&2; tail -30 "$WORK/backend.log" >&2; exit 1; fi
  sleep 1
done
curl -sf "http://127.0.0.1:$PORT/api/health" > /dev/null || { echo "The backend did not answer in time" >&2; tail -30 "$WORK/backend.log" >&2; exit 1; }
echo "   backend on port $PORT"

step "4/6 crawl of the normal interface"
node "$ROOT/scripts/mirror/crawl.mjs" --base "http://127.0.0.1:$PORT" --out "$WORK/site/mirror" \
  --report "$WORK/crawl-report.json" --concurrency "${MIRROR_CONCURRENCY:-4}" --max-file-mb "${MIRROR_MAX_FILE_MB:-8}"
kill "$BACKEND_PID" 2>/dev/null && wait "$BACKEND_PID" 2>/dev/null || true
BACKEND_PID=""

step "5/6 site assembly"
SITE="$WORK/site"
# Netlify: no indexing, no stale copies of the page or of the data (the copy changes every day),
# long caching only for the build's content-hashed files; a view the copy lacks answers 404.
cat > "$SITE/_headers" <<'EOF'
/*
  X-Robots-Tag: noindex, nofollow, noarchive, nosnippet
  Referrer-Policy: no-referrer
  X-Content-Type-Options: nosniff
  X-Frame-Options: DENY
/index.html
  Cache-Control: public, max-age=0, must-revalidate
/mirror/*
  Cache-Control: public, max-age=0, must-revalidate
/assets/*
  Cache-Control: public, max-age=31536000, immutable
EOF
cat > "$SITE/_redirects" <<'EOF'
# Read-only online copy of Paladex (scripts/mirror/build.sh). Existing files are served as they are.
/mirror/*  /mirror-missing.json  404
/api/*     /mirror-missing.json  404
/*         /index.html           200
EOF
printf 'User-agent: *\nDisallow: /\n' > "$SITE/robots.txt"
printf '{"missing": true}\n' > "$SITE/mirror-missing.json"
"$PY" - "$SITE/index.html" <<'EOF'
import sys
p = sys.argv[1]
s = open(p, encoding="utf-8").read()
if 'name="robots"' not in s:
    s = s.replace('<meta charset="UTF-8" />', '<meta charset="UTF-8" />\n    <meta name="robots" content="noindex, nofollow, noarchive" />', 1)
open(p, "w", encoding="utf-8").write(s)
EOF

if [[ "${MIRROR_VERIFY:-}" == "1" ]]; then
  step "   check: open the finished copy"
  VPORT="$(free_port)"
  node "$ROOT/scripts/mirror/serve.mjs" "$SITE" "$VPORT" > "$WORK/serve.log" 2>&1 &
  SERVE_PID=$!
  sleep 1
  node "$ROOT/scripts/mirror/crawl.mjs" --verify "http://127.0.0.1:$VPORT" --plan "$WORK/crawl-report.json" \
    --report "$WORK/verify-report.json" --sample "${MIRROR_VERIFY_SAMPLE:-0}" --concurrency "${MIRROR_CONCURRENCY:-4}"
  kill "$SERVE_PID" 2>/dev/null && wait "$SERVE_PID" 2>/dev/null || true
  SERVE_PID=""
fi

step "6/6 secret check"
"$PY" "$ROOT/scripts/mirror/scan_secrets.py" "$SITE"

rm -rf "$OUT"
mv "$SITE" "$OUT"
cp "$WORK/crawl-report.json" "${OUT%/}.report.json"
[[ -f "$WORK/verify-report.json" ]] && cp "$WORK/verify-report.json" "${OUT%/}.verify.json"
step ""
FILES=$(find "$OUT" -type f | wc -l | tr -d ' ')
JSONS=$(find "$OUT/mirror" -type f -name '*.json' | wc -l | tr -d ' ')
SIZE=$(du -sh "$OUT" | cut -f1)
echo
echo "Online copy ready: $OUT"
echo "  $FILES files, $SIZE ($JSONS recorded answers + manifest in mirror/); crawl report: ${OUT%/}.report.json"
echo "  timings:"
printf '%s' "$TIMINGS"
echo "  total                              $((SECONDS - T_START)) s"
