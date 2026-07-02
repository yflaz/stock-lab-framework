#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="$ROOT/.venv/bin/python"
PORT="${STOCK_LAB_PORT:-8765}"
HOST="${STOCK_LAB_HOST:-0.0.0.0}"

if [ ! -x "$PYTHON_BIN" ]; then
  echo "Missing interpreter: $PYTHON_BIN" >&2
  echo "Create the venv first: python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt" >&2
  exit 1
fi

export STOCK_LAB_PORT="$PORT"
export STOCK_LAB_HOST="$HOST"

# Avoid inheriting unrelated activated virtualenv state from the parent shell.
unset VIRTUAL_ENV PYTHONHOME PYTHONPATH

exec "$PYTHON_BIN" "$ROOT/dashboard_server.py"
