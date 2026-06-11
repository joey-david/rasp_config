#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

exec uv run --python 3.11 \
  --with ultralytics \
  --with pillow \
  --with requests \
  pc_inference/fast_person.py \
  --pi "${PI_URL:-http://192.168.0.43:8080}" \
  --model "${PERSON_MODEL:-yolo11n.pt}" \
  --imgsz "${PERSON_IMGSZ:-640}" \
  --conf "${PERSON_CONF:-0.25}" \
  --hz "${PERSON_HZ:-30}" \
  "$@"
