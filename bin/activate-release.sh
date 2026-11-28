#!/usr/bin/env bash
# Runs on the Pi after upload. Previous releases remain available for rollback.
set -euo pipefail
release=$1
base=$2
service=$3
IFS= read -r password || password=''
as_root() {
    if [[ -n "$password" ]]; then
        printf '%s\n' "$password" | sudo -S -- "$@"
    else
        sudo -n -- "$@"
    fi
}

exec 9>"$base/activate.lock"
flock -n 9 || { echo 'Another release is activating' >&2; exit 1; }
cd "$release"
/usr/bin/python3 -m compileall -q autonomy hardware mischief_common perception skills web robot_api.py
/usr/bin/python3 -c 'import cv2, lgpio, numpy, yaml, PIL'

current="$base/current"
unit="/etc/systemd/system/$service"
previous=$(readlink "$current" || true)
was_active=0
systemctl is-active --quiet "$service" && was_active=1
had_unit=0
if [[ -f "$unit" ]]; then
    as_root cp -p "$unit" "$release/previous.unit"
    had_unit=1
fi
sed -e "s|^WorkingDirectory=.*|WorkingDirectory=$current|" \
    -e "s|^ExecStart=.*|ExecStart=/usr/bin/python3 -u $current/web/web_interface.py|" \
    "systemd/$service" > "$release/new.unit"

switch_to() {
    ln -sfn "$1" "$base/current.next"
    mv -Tf "$base/current.next" "$current"
}

rollback() {
    trap - EXIT
    set +e
    as_root systemctl stop "$service"
    if [[ -n "$previous" ]]; then switch_to "$previous"; else rm -f "$current"; fi
    if (( had_unit )); then
        as_root install -m 644 "$release/previous.unit" "$unit"
    else
        as_root rm -f "$unit"
    fi
    as_root systemctl daemon-reload
    if (( was_active )); then as_root systemctl start "$service"; fi
    echo 'Activation failed. Check the service journal and previous release.' >&2
    exit 1
}
# Check privileges before disturbing the active service.
as_root true
if (( was_active )); then
    curl -fsS --max-time 3 -d '{}' http://127.0.0.1:8080/skill/stop >/dev/null
fi
trap rollback EXIT
as_root systemctl stop "$service"
switch_to "$release"
as_root install -m 644 "$release/new.unit" "$unit"
as_root systemctl daemon-reload
as_root systemctl start "$service"

for attempt in {1..30}; do
    if curl -fs --max-time 2 http://127.0.0.1:8080/api/state | /usr/bin/python3 -c '
import json, sys
try:
    state = json.load(sys.stdin)
except ValueError:
    sys.exit(1)
edge = state["safety"]["edge"]
age = state["camera"]["age"]
sys.exit(0 if age is not None and 0 <= age < .5 and state["safety"]["monitoring"]
         and edge["enabled"] and edge["ready"] and not edge["danger"]
         and state["motion"]["left"] == state["motion"]["right"] == 0 else 1)
'; then
        trap - EXIT
        echo "Active release: $release"
        exit 0
    fi
    sleep 1
done
exit 1
