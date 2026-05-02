
python3 ./spark_runtime.py --verbose launch \
  --env-file .env \
  --mode cluster \
  --hosts spark1 spark2 \
  --preset qwen3.5-397b \
  --tp 2 \
  --log-dir ~/code/build-sglang/logs \

