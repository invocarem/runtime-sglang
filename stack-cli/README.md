# stack-cli

CLI utilities for deploying, launching/stopping, and benchmarking this SGLang stack.

## Folder Layout

- `runtime/spark_runtime.py`: main operations CLI (`deploy`, `launch`, `stop`, `benchmark`, `measure`)
- `tools/benchmark_sglang.py`: wrapper around `python -m sglang.bench_serving`
- `tools/task_benchmark.py`: task-based pass/fail benchmark from JSONL cases
- `tools/benchmark.py`: backward-compatible entrypoint to `benchmark_sglang.py`

## Prerequisites

- Python 3.10+ and a working SGLang environment (`~/.sglang` by default)
- SSH access between nodes (for deploy/remote launch)
- `rsync` installed (required by `deploy`)
- Optional: `.env` in repo root (or pass `--env-file`)

## Quick Start

From repository root:

```bash
cp .env.example .env

python stack-cli/runtime/spark_runtime.py deploy --env-file .env
python stack-cli/runtime/spark_runtime.py launch --mode cluster --env-file .env
python stack-cli/runtime/spark_runtime.py measure --env-file .env
```

## runtime/spark_runtime.py

General form:

```bash
python stack-cli/runtime/spark_runtime.py [--verbose] <subcommand> [args...]
```

### 1) deploy

Sync local sources to remote nodes using `rsync --delete`.

```bash
python stack-cli/runtime/spark_runtime.py deploy \
  --hosts spark-01 spark-02 \
  --remote-dir ~/runtime-sglang
```

Useful flags:

- `--set <name>`: use a named deploy set from `deploy_sets.json`
- `--list-sets`: list deploy sets and exit
- `--sources <csv>`: override synced paths
- `--exclude <csv>`: override rsync excludes
- `--ssh-key`, `--ssh-port`
- `--env-file <path>`

### 2) launch

Start SGLang server in `solo` (local/single host) or `cluster` mode.

```bash
# Solo local
python stack-cli/runtime/spark_runtime.py launch --mode solo --preset qwen3.5-2b

# Solo remote
python stack-cli/runtime/spark_runtime.py launch --mode solo --host spark-02 --preset qwen3.5-2b

# Cluster
python stack-cli/runtime/spark_runtime.py launch \
  --mode cluster \
  --hosts spark-01 spark-02 \
  --dist-addr spark-01:20000 \
  --preset qwen3.6-27b
```

Useful flags:

- `--preset <name>`, `--presets-file <path>`, `--list-presets`
- `--model-path`, `--venv`, `--tp`, `--port`
- `--sglang-args "<extra flags>"`
- `--command "<full command override>"`
- `--log-file` (solo), `--log-dir` (cluster), `--env-file`

Notes:

- In `solo` mode, default `tp=1` unless `--tp` is passed.
- In `cluster` mode, each host gets a `--node-rank` based on host order.
- When using `--preset`, `--served-model-name <preset>` is auto-added unless already provided in args.

### 3) stop

Stop SGLang server in `solo` (local/single host) or `cluster` mode.

```bash
# Solo local
python stack-cli/runtime/spark_runtime.py stop --mode solo

# Solo remote
python stack-cli/runtime/spark_runtime.py stop --mode solo --host spark-02 --port 30000

# Cluster
python stack-cli/runtime/spark_runtime.py stop \
  --mode cluster \
  --hosts spark-01 spark-02 \
  --port 30000
```

Useful flags:

- `--port` (defaults via CLI/.env/preset resolution)
- `--grace-sec` (wait before force-kill)
- `--preset`, `--presets-file`, `--env-file`

### 4) benchmark

Send repeated `/v1/chat/completions` requests and print latency/throughput JSON.

```bash
python stack-cli/runtime/spark_runtime.py benchmark \
  --base-url http://spark-01:30000 \
  --model default \
  --requests 50
```

### 5) measure

Capture `nvidia-smi` + system load snapshots locally or over SSH.

```bash
# local
python stack-cli/runtime/spark_runtime.py measure

# remote hosts
python stack-cli/runtime/spark_runtime.py measure --hosts spark-01 spark-02
```

## Model Presets

Preset defaults are read from `model_presets.json` (or `MODEL_PRESETS_FILE` / `--presets-file`).

List available presets:

```bash
python stack-cli/runtime/spark_runtime.py launch --list-presets
```

Launch with preset and override selected fields:

```bash
python stack-cli/runtime/spark_runtime.py launch \
  --mode solo \
  --preset qwen3.5-397b \
  --tp 2 \
  --port 31000
```

## Environment Variables (.env)

Common keys consumed by `spark_runtime.py`:

- Cluster: `MASTER_NODE`, `WORKER_NODE`, `MASTER_PORT`, `DIST_ADDR`
- Server: `SERVER_PORT`, `MODEL_PATH`, `TP_SIZE`, `VENV_PATH`
- Presets/deploy: `MODEL_PRESET`, `MODEL_PRESETS_FILE`, `DEPLOY_SET`, `DEPLOY_SETS_FILE`, `REMOTE_DIR`
- Launch extras: `SGLANG_EXTRA_ARGS`
- NCCL/runtime exports: `NCCL_*`, `CUDA_GRAPHS`, `SGLANG_DISABLE_TORCHVISION`

Precedence is generally: CLI flags > `.env` > preset values > built-in defaults.

## tools/benchmark_sglang.py

Wrapper for `sglang.bench_serving` with stack defaults and served-model auto-detection.

```bash
python stack-cli/tools/benchmark_sglang.py \
  --base-url http://127.0.0.1:30000 \
  --dataset-name random \
  --num-prompts 128 \
  --model qwen3.5-2b
```

Environment variables:

- `BENCHMARK_BASE_URL`, `BENCHMARK_BACKEND`, `BENCHMARK_DATASET`
- `BENCHMARK_NUM_PROMPTS`, `BENCHMARK_RANDOM_INPUT_LEN`, `BENCHMARK_RANDOM_OUTPUT_LEN`
- `BENCHMARK_SERVED_MODEL`, `BENCHMARK_HF_MODEL`, `BENCHMARK_TOKENIZER`
- `BENCHMARK_MAX_CONCURRENCY`, `BENCHMARK_EXTRA_REQUEST_BODY`
- `BENCHMARK_PRESERVE_SEPARATE_REASONING`, `BENCHMARK_PRESERVE_THINKING`

## tools/task_benchmark.py

Task-style benchmark with per-case checkers (`regex`, `contains`, `contains_all`) from JSONL.

```bash
python stack-cli/tools/task_benchmark.py \
  --input stack-cli/tools/task_benchmark_seed.jsonl \
  --base-url http://127.0.0.1:30000
```

Environment variables:

- `TASK_BENCH_INPUT`, `TASK_BENCH_BASE_URL`, `TASK_BENCH_MODEL`
- `TASK_BENCH_TEMPERATURE`, `TASK_BENCH_MAX_TOKENS`, `TASK_BENCH_TIMEOUT_SEC`
- `TASK_BENCH_PRESERVE_SEPARATE_REASONING`, `TASK_BENCH_PRESERVE_THINKING`

## Troubleshooting

- `No hosts provided`: pass `--hosts` or set `MASTER_NODE`/`WORKER_NODE`.
- `Presets file not found`: verify `model_presets.json` path or pass `--presets-file`.
- `Missing venv activate script`: pass `--venv` or set `VENV_PATH` correctly.
- `No successful benchmark requests`: verify server is running and `--base-url` is reachable.
