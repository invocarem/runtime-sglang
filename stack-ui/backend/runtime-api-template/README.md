# Reusable SGLang Runtime API Template

This folder is designed to be copied into your separate `sglang_runtime` project.

## Included APIs

- `GET /healthz`
- `GET /v1/models`
- `GET /v1/metrics`
- `POST /v1/chat/completions`
- `POST /v1/benchmark/load`
- `POST /v1/benchmark/task`

## Why this template

- Keeps transport (`routes.ts`) separate from logic (`services.ts`).
- Keeps SGLang HTTP wiring in one adapter (`sglang-adapter.ts`).
- Reuses robust completion parsing (`openai-completion-text.ts`).
- Avoids dashboard-specific dependencies and giant route files.

## Expected env vars

- `SGLANG_BASE_URL` (default `http://127.0.0.1:30000`)
- `SGLANG_METRICS_URL` (optional override)
- `SGLANG_METRICS_PATH` (default `/metrics`)
- `SGLANG_ALLOW_ANY_HOST=1` (optional; disables localhost-only safety)
- `SGLANG_REQUEST_TIMEOUT_MS` (default `120000`)
- `RUNTIME_API_PORT` (default `8788`)

## Run example

If your runtime project uses `tsx`:

`tsx server/runtime-api-template/server.ts`

## Task benchmark input format

`POST /v1/benchmark/task` expects:

```json
{
  "model": "Qwen/Qwen3-8B",
  "temperature": 0.2,
  "max_tokens": 512,
  "tasks": [
    {
      "id": "t1",
      "category": "math",
      "prompt": "What is 6 * 7?",
      "checker": { "type": "contains", "value": "42" }
    }
  ]
}
```

