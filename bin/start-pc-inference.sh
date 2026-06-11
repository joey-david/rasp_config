#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

exec uv run --python 3.11 \
  --with ultralytics \
  --with pillow \
  pc_inference/fast_person.py \
  --host "${DETECT_HOST:-0.0.0.0}" \
  --port "${DETECT_PORT:-8081}" \
  --model "${PERSON_MODEL:-yolo11n.pt}" \
  --imgsz "${PERSON_IMGSZ:-640}" \
  --conf "${PERSON_CONF:-0.25}" \
  "$@"
