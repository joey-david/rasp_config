#!/usr/bin/env bash
set -euo pipefail

PI_HOST="${PI_HOST:-rpi}"
PI_DIR="${PI_DIR:-/home/joey}"

cd "$(dirname "$0")/.."

rsync -az --delete --delete-excluded \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  hardware memory mischief_common perception reasoning skills systemd web \
  motion_udp.py requirements.txt robot_api.py web_interface.py progress.md .gitignore \
  "$PI_HOST:$PI_DIR/"

ssh "$PI_HOST" "rm -rf \
  '$PI_DIR/lock_on.py' \
  '$PI_DIR/tracker.py' \
  '$PI_DIR/skills/find.py' \
  '$PI_DIR/skills/goto.py' \
  '$PI_DIR/skills/examples' \
  '$PI_DIR/timelapse_100x.h264'"
