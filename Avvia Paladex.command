#!/usr/bin/env bash
# Parodi Group — Honey Intelligence: start script for macOS / Linux.
# macOS: double-click "Avvia Paladex.command" (same script). Linux: ./start.sh
# Options are passed on to `python -m paladex serve` (e.g. ./start.sh --no-browser).
set -euo pipefail
cd "$(dirname "$0")"
# Programs installed with Homebrew on a Mac (a newer Python, the optional Tesseract OCR) even when
# the Terminal does not list their folder.
export PATH="$PATH:/opt/homebrew/bin:/usr/local/bin"

# A Python that runs and is 3.11 or newer (the macOS built-in python3 is often 3.9).
python_ok() { "$1" -c 'import sys; sys.exit(sys.version_info < (3, 11))' >/dev/null 2>&1; }

# The application's own Python: created on the first start, and again when it no longer runs or
# is too old (Python removed or replaced on this computer).
if ! python_ok backend/.venv/bin/python; then
  PY=""
  for c in ${PYTHON:-} python3.15 python3.14 python3.13 python3.12 python3.11 python3; do
    p="$(command -v "$c" 2>/dev/null)" || continue
    # Apple's own /usr/bin/python3 is 3.9, or a window offering to install the developer tools.
    if [ "$p" = /usr/bin/python3 ] && [ "$(uname)" = Darwin ]; then continue; fi
    if python_ok "$p"; then PY="$p"; break; fi
  done
  if [ -z "$PY" ]; then
    echo
    echo "  Python 3.11 o superiore non trovato: installarlo da https://www.python.org/downloads/ e riaprire Paladex."
    echo "  Python 3.11 or newer not found: install it from https://www.python.org/downloads/ and start Paladex again."
    echo
    exit 1
  fi
  echo "  Prima installazione: preparo l'ambiente (qualche minuto)..."
  echo "  First start: preparing the environment (a few minutes)..."
  rm -rf backend/.venv
  if ! "$PY" -m venv backend/.venv; then
    echo "  Impossibile preparare l'ambiente di Python. / Could not create the Python environment."; exit 1
  fi
  backend/.venv/bin/python -m pip install --upgrade pip >/dev/null 2>&1 || true
  if ! backend/.venv/bin/python -m pip install -r backend/requirements.txt; then
    echo
    echo "  Installazione non riuscita: controllare la connessione internet e riaprire Paladex."
    echo "  Installation failed: check the internet connection and start Paladex again."
    echo
    exit 1
  fi
fi
if [ ! -f frontend/dist/index.html ]; then
  if command -v npm >/dev/null; then
    (cd frontend && (npm ci || npm install) && npm run build)
  else
    echo "ATTENZIONE: interfaccia non compilata e Node.js non installato (vedere README.md)"
  fi
fi
[ -f .env ] || (umask 077 && cp .env.example .env)     # the keys file: readable by this user only
# Update (git pull), libraries if they changed, then start. `exec`: this shell is gone before an
# update can rewrite this file.
exec backend/.venv/bin/python scripts/launch.py "$@"
