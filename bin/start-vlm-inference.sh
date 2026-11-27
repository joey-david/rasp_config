#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

model="${VLM_MODEL:-mlx-community/Qwen3-VL-8B-Instruct-4bit}"

exec .venv/bin/python -m mlx_vlm.server \
  --host "${VLM_INFERENCE_HOST:-127.0.0.1}" \
  --port "${VLM_INFERENCE_PORT:-8000}" \
  --model "$model" \
  --max-kv-size "${VLM_MAX_KV_SIZE:-4096}" \
  "$@"
