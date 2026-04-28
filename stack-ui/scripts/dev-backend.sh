#!/usr/bin/env bash
# Run FastAPI on this host. On a cluster worker, set:
#   STACK_UI_BIND_HOST=0.0.0.0   (legacy: BENCHMARK_UI_BIND_HOST)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/backend"
BIND="${STACK_UI_BIND_HOST:-${BENCHMARK_UI_BIND_HOST:-127.0.0.1}}"
PORT="${STACK_UI_PORT:-${BENCHMARK_UI_PORT:-8765}}"
# Use `python -m uvicorn`, not `.venv/bin/uvicorn`: the shim shebang breaks if the
# venv was copied from another machine or Python moved ("cannot execute: required file not found").
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
elif ! .venv/bin/python -m uvicorn --help >/dev/null 2>&1; then
  .venv/bin/pip install -r requirements.txt
fi
exec .venv/bin/python -m uvicorn main:app --reload --host "$BIND" --port "$PORT"
