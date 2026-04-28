# README

Runtime Sglang

1. use .sglang enivironment
```
source ~/.sglang/bin/activate
uv pip list | grep sglang
Using Python 3.12.3 environment at: .sglang
sglang                       0.5.10.post2.dev704+g0c826374a /home/chenchen/code/build-sglang/sglang/python
sglang-kernel                0.4.1
torch                        2.13.0a0+gitdff4497            /home/chenchen/code/build-sglang/pytorch
torchvision                  0.27.0a0+499ca51               /home/chenchen/code/build-sglang/vision

```
2. build wheel
```

cd sglang/sgl-kernel
TORCH_CUDA_ARCH_LIST="12.1a" MAX_JOBS=4 CMAKE_BUILD_PARALLEL_LEVEL=1  python -m build --wheel --no-isolation
uv pip install --no-deps dist/sglang_kernel-0.4.1-cp310-abi3-linux_aarch64.whl
```

3. build pytorch and verify
```
python -c "
import torch
print('PyTorch version:', torch.__version__)
print('CUDA archs:', torch.cuda.get_arch_list())
print('CUDA version:', torch.version.cuda)
"
PyTorch version: 2.13.0a0+gitdff4497
CUDA archs: ['sm_121']
CUDA version: 13.0
```

4. build torch vision
```
git clone https://github.com/pytorch/vision.git
cd vision

```

my mistake may be is I did not checkout dff4497 (the commit match with torch )
git checkout dff44973f3eba04a92de8499c17cd237997140f2

so far I did not do anything for audio.

## 5. Python ops CLI for two DGX Spark nodes

Use `stack-cli/runtime/spark_runtime.py` for deploy, launch, benchmark, and measurement.

### Use `.env` (recommended simple flow)
```bash
cp .env.example .env

python stack-cli/runtime/spark_runtime.py deploy --env-file .env
python stack-cli/runtime/spark_runtime.py launch --mode cluster --env-file .env
python stack-cli/runtime/spark_runtime.py measure --env-file .env
```

`.env` keys supported:
- `MASTER_NODE`, `WORKER_NODE`
- `MASTER_PORT`, `SERVER_PORT`
- `MODEL_PATH`, `TP_SIZE`, `VENV_PATH` — **`--mode solo` uses `tp=1`**, ignoring preset `tp` and `TP_SIZE`, unless you pass **`--tp`**. **`--mode cluster`** still resolves `tp` from preset, then `TP_SIZE`, then `--tp`.
- `REMOTE_DIR`, `DIST_ADDR`
- `MODEL_PRESET`, `MODEL_PRESETS_FILE`, `SGLANG_EXTRA_ARGS`
- NCCL/CUDA/SGLANG env vars (exported before launch)

### Deploy to another Spark
```bash
python stack-cli/runtime/spark_runtime.py deploy \
  --hosts spark-02 \
  --remote-dir ~/runtime-sglang
```

### Launch server (solo)
```bash
# Local node
python stack-cli/runtime/spark_runtime.py launch --mode solo --model-path ~/huggingface/Qwen_Qwen3.5-2B

# Remote node
python stack-cli/runtime/spark_runtime.py launch --mode solo --host spark-02 --model-path ~/huggingface/Qwen_Qwen3.5-2B
```

### Launch with model presets
```bash
# Create editable presets file from example
cp model_presets.json.example model_presets.json

# Inspect available presets
python stack-cli/runtime/spark_runtime.py launch --list-presets

# Launch with a preset
python stack-cli/runtime/spark_runtime.py launch --mode solo --preset qwen3.5-2b

# Override preset values when needed
python stack-cli/runtime/spark_runtime.py launch --mode solo --preset qwen3.5-397b --tp 16 --port 31000

# Add extra launch flags on top of preset/.env
python stack-cli/runtime/spark_runtime.py launch --mode solo --preset qwen3.5-2b \
  --sglang-args "--context-length 65536 --mem-fraction-static 0.8 --enable-metrics --trust-remote-code"
```

### Launch cluster (2 nodes)
```bash
python stack-cli/runtime/spark_runtime.py launch \
  --mode cluster \
  --hosts spark-01 spark-02 \
  --dist-addr spark-01:20000 \
  --model-path ~/huggingface/Qwen_Qwen3.5-2B
```

### Benchmark runtime
```bash
python stack-cli/runtime/spark_runtime.py benchmark \
  --base-url http://spark-01:30000 \
  --model default \
  --requests 50
```

### Measure utilization
```bash
# local snapshot
python stack-cli/runtime/spark_runtime.py measure

# both nodes
python stack-cli/runtime/spark_runtime.py measure --hosts spark-01 spark-02
```

Notes:
- `deploy` uses `rsync --delete` to keep remote directory aligned with local selected sources.
- `launch --mode cluster` starts one process per host with `--node-rank` assigned by host order.
- Preset precedence is: `--command` override > CLI values > `.env` values > preset values > built-in defaults.
- When a preset is selected, launch auto-adds `--served-model-name <preset>` unless already provided in extra args.
- `sglang_args` in preset JSON is a token list; flags without values are single items (example: `--enable-metrics`).
- `benchmark` targets OpenAI-compatible `/v1/chat/completions`.