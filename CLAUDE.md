# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This repository is a DGX Spark runtime for serving LLMs via SGLang. It orchestrates deploying, launching, benchmarking, and monitoring SGLang inference servers across one or two NVIDIA DGX Spark nodes (spark1, spark2). The target hardware uses CUDA 13.0 with `sm_121` architecture.

## Repository Structure

The repo has two categories of content:

**Original project code (actively developed here):**
- `stack-cli/runtime/spark_runtime.py` — Core CLI with subcommands: `deploy`, `launch`, `stop`, `benchmark`, `measure`
- `stack-cli/tools/` — Model download (`download.py`), model transfer between hosts (`model_transfer.py`), benchmark wrappers (`benchmark_sglang.py`, `task_benchmark.py`)
- `stack-ui/` — Web UI for the runtime: FastAPI backend (`backend/main.py`) and Vite/TypeScript frontend (`frontend/`)
- `spark_runtime.py` — Backward-compatible shim that delegates to `stack-cli/runtime/spark_runtime.py`
- `definitions.json` — Tool definitions consumed by the Stack UI
- `model_presets.json.example` — Template for model launch presets (copy to `model_presets.json` to use)
- `tests/` — Unit tests for `spark_runtime` helpers (no SSH/rsync needed)
- `utils/` — Build verification scripts for the vendor packages:
  - `utils/check_sgl.py` — Confirms sgl_kernel and PyTorch are linked (prints versions, CUDA archs)
  - `utils/check_torch.py` — Validates torchvision forward pass and torchaudio CUDA ops

**Vendor copies (synced from upstream repos, not edited here):**
- `sglang/` — SGLang source (editable install)
- `pytorch/` — PyTorch source (built from source for CUDA 13.0 / sm_121)
- `vision/` — TorchVision source
- `audio/` — TorchAudio source

These are excluded in `.claudeignore` and should not be modified in this repo.

## Environment

- Python environment lives in `.sglang/` (a local venv). Activate with `source .sglang/bin/activate`.
- Configuration is in `.env` (copied from `.env.example`). Key variables: `MASTER_NODE`, `WORKER_NODE`, `SERVER_PORT`, `MODEL_PATH`, `TP_SIZE`, NCCL/RoCE settings.
- The `.sglang` venv contains editable installs of sglang, sglang-kernel, pytorch, and torchvision built for the DGX Spark GPU.

## Common Commands

### Build Verification

After building or updating the vendor packages, run these to confirm everything links correctly:

```bash
# Verify sgl_kernel + PyTorch
python utils/check_sgl.py

# Verify torchvision + torchaudio CUDA ops
python utils/check_torch.py
```

### Tests
```bash
npm run test
# Or directly:
python3 -m pytest tests/test_spark_runtime.py tests/test_spark_runtime_deploy.py tests/test_spark_runtime_ops.py
```

### Runtime CLI (from repo root)
```bash
# Deploy to remote node(s)
python stack-cli/runtime/spark_runtime.py deploy --env-file .env

# Launch server
python stack-cli/runtime/spark_runtime.py launch --mode solo --preset qwen3.5-2b --env-file .env
python stack-cli/runtime/spark_runtime.py launch --mode cluster --env-file .env

# Stop server
python stack-cli/runtime/spark_runtime.py stop --mode cluster --env-file .env

# Benchmark
python stack-cli/runtime/spark_runtime.py benchmark --base-url http://spark-01:30000 --model default --requests 50

# Measure GPU/CPU utilization
python stack-cli/runtime/spark_runtime.py measure --hosts spark-01 spark-02
```

The root `spark_runtime.py` is a backward-compatible shim — the real implementation is in `stack-cli/runtime/spark_runtime.py`.

### Stack UI Development
```bash
# Full dev server (backend + frontend)
cd stack-ui && npm run dev

# Or run individually:
npm run backend   # FastAPI on :8765
npm run frontend   # Vite dev server (waits for backend)
```

Backend binds to `STACK_UI_BIND_HOST` (default `127.0.0.1`) on port `STACK_UI_PORT` (default `8765`). Set `STACK_UI_BIND_HOST=0.0.0.0` to expose on cluster nodes.

### Model Management
```bash
# Download model from HuggingFace
python stack-cli/tools/download.py --model-id Qwen/Qwen3.5-32B --save-dir /data/hf

# Transfer model between hosts
python stack-cli/tools/model_transfer.py --mode rdma --src /data/hf/model --dest /data/hf/model --rank 0 --world-size 2 --master-addr <IP> --master-port 29500
```

## Key Architectural Details

**Launch modes:** `solo` (single host, `tp=1` by default) vs `cluster` (multi-host, assigns `--node-rank` by host order).

**Preset precedence:** CLI flags > `.env` > `model_presets.json` preset values > built-in defaults.

**Model presets:** Defined in `model_presets.json` (create from `.example`). Each preset has `model_path`, `tp`, `port`, `venv_path`, and `sglang_args`. When a preset is used, `--served-model-name <preset>` is auto-added.

**Deploy:** Uses `rsync --delete` to mirror local sources to remote `REMOTE_DIR`. Configurable deploy sets via `deploy_sets.json`.

**Stack UI:** FastAPI backend (`stack-ui/backend/main.py`) proxies to the SGLang server and provides tool endpoints defined in `definitions.json` (health, models, metrics, chat smoke test, load/task benchmark).
