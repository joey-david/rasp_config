#!/usr/bin/env bash
set -euo pipefail

PI_HOST="${PI_HOST:-rpi}"
PI_DIR="${PI_DIR:-/home/joey}"
SERVICE="${SERVICE:-mischief-bot.service}"
# These values enter remote shell commands and systemd path directives.
[[ "$PI_DIR" =~ ^/[a-zA-Z0-9_./-]+$ && "$SERVICE" =~ ^[a-zA-Z0-9_-]+\.service$ ]] || exit 2
cd "$(dirname "$0")/.."

base="$PI_DIR/.local/share/mischief-bot"
release=$(ssh "$PI_HOST" "mkdir -p '$base/releases' && mktemp -d '$base/releases/$(git rev-parse --short HEAD).XXXXXXXX'")
rsync -az --exclude='__pycache__/' --exclude='*.pyc' --exclude='odometry/angular_*/' \
  autonomy calibrations hardware mischief_common perception skills systemd web \
  requirements.txt robot_api.py bin/activate-release.sh "$PI_HOST:$release/"

# Supply sudo's input on stdin so the password stays out of the remote command.
printf '%s\n' "${PI_SUDO_PASSWORD:-}" | ssh "$PI_HOST" "bash '$release/activate-release.sh' '$release' '$base' '$SERVICE'"
