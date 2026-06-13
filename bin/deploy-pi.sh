#!/usr/bin/env bash
set -euo pipefail

PI_HOST="${PI_HOST:-rpi}"
PI_DIR="${PI_DIR:-/home/joey}"
SERVICE="${SERVICE:-mischief-bot.service}"
PI_SUDO_PASSWORD="rasppi314"

cd "$(dirname "$0")/.."

rsync -az --delete --delete-excluded \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  hardware mischief_common perception skills systemd web \
  requirements.txt robot_api.py progress.md .gitignore \
  "$PI_HOST:$PI_DIR/"

ssh "$PI_HOST" "rm -rf \
  '$PI_DIR/web_interface.py' \
  '$PI_DIR/lock_on.py' \
  '$PI_DIR/tracker.py' \
  '$PI_DIR/skills/find.py' \
  '$PI_DIR/skills/goto.py' \
  '$PI_DIR/skills/examples' \
  '$PI_DIR/memory' \
  '$PI_DIR/reasoning' \
  '$PI_DIR/perception/backends' \
  '$PI_DIR/timelapse_100x.h264'"

ssh "$PI_HOST" \
  "PI_DIR='$PI_DIR' SERVICE='$SERVICE' PI_SUDO_PASSWORD='${PI_SUDO_PASSWORD:-}' bash -s" <<'REMOTE'
set -euo pipefail

sudo_run() {
  if [ -n "${PI_SUDO_PASSWORD:-}" ]; then
    printf '%s\n' "$PI_SUDO_PASSWORD" | sudo -S "$@"
  else
    sudo -n "$@"
  fi
}

if ! cmp -s "$PI_DIR/systemd/$SERVICE" "/etc/systemd/system/$SERVICE"; then
  sudo_run cp "$PI_DIR/systemd/$SERVICE" "/etc/systemd/system/$SERVICE"
fi
sudo_run systemctl daemon-reload
sudo_run systemctl restart "$SERVICE"
systemctl is-active --quiet "$SERVICE"
systemctl --no-pager --full status "$SERVICE" | sed -n '1,12p'
REMOTE
