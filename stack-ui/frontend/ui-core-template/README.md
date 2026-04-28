# Reusable SGLang Runtime UI Core

This folder is a copy-ready UI core for projects like `sglang-runtime`.

It keeps shared product surfaces:

- Chat sidebar
- Metrics tab
- Benchmark tab (load + task)
- Tools tab shell (backend-defined)

And intentionally leaves launch/deploy behavior outside the core (project-specific).

## What to copy

Copy this whole folder into your target project and wire it as your frontend app root.

## Core API contract

The UI expects the following backend routes:

- `GET /api/config`
  - returns `{ inferenceBaseUrl?: string, metricsUrl?: string, defaultModel?: string, error?: string }`
- `POST /api/chat/completions`
  - OpenAI-compatible response shape (`choices[0].message.content` etc.)
- `GET /api/metrics`
  - success: `{ ok: true, highlightLines: string[], rawPreview: string, rawTruncated?: boolean, fetchedAt?: string }`
  - error: `{ ok: false, error: string, bodyPreview?: string }`
- `POST /api/benchmark`
  - same schema as this dashboard's load benchmark endpoint
- `POST /api/benchmark/task`
  - same schema as this dashboard's task benchmark endpoint
- `GET /api/tools/definitions`
  - optional
  - returns `{ tools: Array<{ id: string, label: string, description?: string, schema?: unknown }> }`
- `POST /api/tools/run`
  - optional
  - request: `{ tool: string, args: Record<string, unknown> }`
  - response: `{ ok: boolean, output?: unknown, error?: string }`

`/api/tools/*` is optional. If absent, the Tools tab remains a helpful placeholder for project-specific wiring.

## Launch/Deploy ownership

This UI core does not include Launch/Deploy logic.
Add your own launch page/module in your runtime project if needed.

## Files

- `index.html`: Layout shell and tab panels
- `src/main.ts`: app entry
- `src/app/init.ts`: bootstraps feature modules
- `src/features/chat.ts`: chat sidebar
- `src/features/metrics.ts`: metrics tab
- `src/features/benchmark.ts`: benchmark tab
- `src/features/tools.ts`: generic tool runner (optional backend)
- `src/lib/*`: shared helpers (API + model preferences + completion parsing)
- `src/styles.css`: shared styling

