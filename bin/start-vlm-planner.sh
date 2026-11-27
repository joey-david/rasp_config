#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

export VLM_BASE_URL="${VLM_BASE_URL:-http://127.0.0.1:8000/v1}"
export VLM_MODEL="${VLM_MODEL:-mlx-community/Qwen3-VL-8B-Instruct-4bit}"
export VLM_MAX_TOKENS="${VLM_MAX_TOKENS:-160}"

exec .venv/bin/python pc_inference/vlm_server.py \
  --host "${VLM_PLANNER_HOST:-0.0.0.0}" \
  --port "${VLM_PLANNER_PORT:-8090}" \
  "$@"
