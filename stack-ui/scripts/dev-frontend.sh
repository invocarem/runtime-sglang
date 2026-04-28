#!/usr/bin/env bash
# Wait for API then start Vite. Set STACK_UI_EXPOSE_DEV=1 on a worker (legacy: BENCHMARK_UI_EXPOSE_DEV).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# Set frontend/backend dev defaults here (without loading .env).
export STACK_UI_BIND_HOST="${STACK_UI_BIND_HOST:-0.0.0.0}"
export STACK_UI_EXPOSE_DEV="${STACK_UI_EXPOSE_DEV:-1}"
export STACK_UI_ALLOW_LAUNCH="${STACK_UI_ALLOW_LAUNCH:-1}"
export STACK_UI_ACCESS_LOG="${STACK_UI_ACCESS_LOG:-1}"
export SGLANG_ALLOW_ANY_HOST="${SGLANG_ALLOW_ANY_HOST:-1}"
export SGLANG_BASE_URL="${SGLANG_BASE_URL:-http://100.109.56.33:30000}"
PORT="${STACK_UI_PORT:-${BENCHMARK_UI_PORT:-8765}}"
npm exec -- wait-on "http-get://127.0.0.1:${PORT}/health"
cd "$ROOT/frontend"
exec npm exec vite
