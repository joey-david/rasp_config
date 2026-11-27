#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

UV_BIN="${UV_BIN:-/opt/homebrew/bin/uv}"

exec "$UV_BIN" run --python 3.11 \
  --with mlx \
  --with mlx-embedding-models \
  --with 'transformers<5' \
  --with ultralytics \
  --with pillow \
  pc_inference/object_detection.py \
  --host "${DETECT_HOST:-0.0.0.0}" \
  --port "${DETECT_PORT:-8081}" \
  --model "${OBJECT_MODEL:-yolo11s.pt}" \
  --imgsz "${OBJECT_IMGSZ:-640}" \
  --conf "${OBJECT_CONF:-0.15}" \
  "$@"
