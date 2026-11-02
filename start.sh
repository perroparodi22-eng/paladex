#!/usr/bin/env bash
# Parodi Group — Honey Intelligence: start script for macOS / Linux.
# macOS: double-click "Avvia Paladex.command" (same script).
set -euo pipefail
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null; then
  echo "Python 3.11+ non trovato: installarlo da https://www.python.org/downloads/"; exit 1
fi
if [ ! -x backend/.venv/bin/python ]; then
  echo "Prima installazione: preparo l'ambiente (qualche minuto)..."
  "$PY" -m venv backend/.venv
  backend/.venv/bin/python -m pip install --upgrade pip >/dev/null
  backend/.venv/bin/python -m pip install -r backend/requirements.txt
fi
if [ ! -f frontend/dist/index.html ]; then
  if command -v npm >/dev/null; then
    (cd frontend && (npm ci || npm install) && npm run build)
  else
    echo "ATTENZIONE: interfaccia non compilata e Node.js non installato (vedere README.md)"
  fi
fi
[ -f .env ] || cp .env.example .env
cd backend && exec .venv/bin/python -m paladex serve
