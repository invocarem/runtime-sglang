#!/usr/bin/env bash
# Wait for API then start Vite. Set STACK_UI_EXPOSE_DEV=1 on a worker (legacy: BENCHMARK_UI_EXPOSE_DEV).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${STACK_UI_PORT:-${BENCHMARK_UI_PORT:-8765}}"
wait-on "http-get://127.0.0.1:${PORT}/health"
cd "$ROOT/frontend"
exec npm exec vite
