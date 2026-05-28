#!/usr/bin/env bash
set -euo pipefail

# Motor A test for current pin-27-through-40 layout.
# TB6612FNG wiring:
#   STBY -> GPIO26, physical pin 37
#   APWM -> GPIO12, physical pin 32
#   AIN1 -> GPIO16, physical pin 36
#   AIN2 -> GPIO6,  physical pin 31

standby=26
apwm=12
ain1=16
ain2=6

duration="${1:-5}"
mode="${2:-both}" # both | forward | reverse | hold-forward | hold-reverse

all_low() {
  pinctrl set "$apwm" op dl || true
  pinctrl set "$ain1" op dl || true
  pinctrl set "$ain2" op dl || true
  pinctrl set "$standby" op dl || true
}

dump() {
  echo "== pin states =="
  for p in "$standby" "$apwm" "$ain1" "$ain2"; do
    pinctrl get "$p" || true
  done
  vcgencmd get_throttled 2>/dev/null || true
}

run_dir() {
  local dir="$1"
  local seconds="$2"
  echo "== A $dir for ${seconds}s =="
  pinctrl set "$standby" op dh
  pinctrl set "$apwm" op dl
  if [[ "$dir" == "forward" ]]; then
    pinctrl set "$ain1" op dh
    pinctrl set "$ain2" op dl
  elif [[ "$dir" == "reverse" ]]; then
    pinctrl set "$ain1" op dl
    pinctrl set "$ain2" op dh
  else
    echo "unknown direction: $dir" >&2
    exit 2
  fi
  pinctrl set "$apwm" op dh
  dump
  sleep "$seconds"
  pinctrl set "$apwm" op dl
  pinctrl set "$ain1" op dl
  pinctrl set "$ain2" op dl
  sleep 0.5
}

trap all_low EXIT INT TERM
all_low

echo "Motor A pins: STBY=GPIO${standby}/pin37 APWM=GPIO${apwm}/pin32 AIN1=GPIO${ain1}/pin36 AIN2=GPIO${ain2}/pin31"
echo "Usage: $0 [seconds] [both|forward|reverse|hold-forward|hold-reverse]"
dump

case "$mode" in
  both)
    run_dir forward "$duration"
    run_dir reverse "$duration"
    ;;
  forward)
    run_dir forward "$duration"
    ;;
  reverse)
    run_dir reverse "$duration"
    ;;
  hold-forward)
    echo "Holding A forward until Ctrl-C"
    pinctrl set "$standby" op dh
    pinctrl set "$ain1" op dh
    pinctrl set "$ain2" op dl
    pinctrl set "$apwm" op dh
    dump
    while true; do sleep 5; vcgencmd get_throttled 2>/dev/null || true; done
    ;;
  hold-reverse)
    echo "Holding A reverse until Ctrl-C"
    pinctrl set "$standby" op dh
    pinctrl set "$ain1" op dl
    pinctrl set "$ain2" op dh
    pinctrl set "$apwm" op dh
    dump
    while true; do sleep 5; vcgencmd get_throttled 2>/dev/null || true; done
    ;;
  *)
    echo "unknown mode: $mode" >&2
    exit 2
    ;;
esac

all_low
echo "== stopped =="
dump
