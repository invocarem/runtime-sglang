SGLANG_LOG_LEVEL=DEBUG \
SGLANG_ENABLE_PROFILE=1 \
 SGLANG_DISABLE_VISION=1 \
python3 -m sglang.launch_server --model-path ~/huggingface/Qwen_Qwen3.5-2B  \
  --trust-remote-code \
  --tp 1 \
  --attention-backend flashinfer \
  --tool-call-parser qwen3_coder \
  --reasoning-parser qwen3 \
  --mem-fraction-static 0.7 \
  --max-running-requests 8 \
  --log-level info \
  --host 0.0.0.0 \
  --port 30000
