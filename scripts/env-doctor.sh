#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STOCK_PY="$ROOT/.venv/bin/python"

echo "=== shell env ==="
env | egrep '^(PATH|VIRTUAL_ENV|PYTHONHOME|PYTHONPATH)=' || true

echo
echo "=== command resolution ==="
for cmd in python python3 pip pip3; do
  echo "--- $cmd ---"
  type -a "$cmd" || true
  echo
done

echo "=== stock_lab venv ==="
echo "python: $STOCK_PY"
"$STOCK_PY" --version
"$STOCK_PY" -m pip --version

echo
echo "=== symlinks ==="
readlink -f "$(command -v python3)" || true
readlink -f "$(command -v pip)" || true
readlink -f "$(command -v pip3)" || true
