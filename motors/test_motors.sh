#!/usr/bin/env bash
set -euo pipefail

standby=19
apwm=6
ain1=16
ain2=13
bpwm=4
bin1=17
bin2=5

dump() {
  echo "== pin states =="
  for p in "$standby" "$apwm" "$ain1" "$ain2" "$bpwm" "$bin1" "$bin2"; do
    pinctrl get "$p" || true
  done
}

all_low() {
  for p in "$apwm" "$ain1" "$ain2" "$bpwm" "$bin1" "$bin2" "$standby"; do
    pinctrl set "$p" op dl
  done
}

run_motor() {
  local name="$1" pwm="$2" in1="$3" in2="$4" dir="$5" dur="$6"
  echo "== $name $dir for ${dur}s =="
  pinctrl set "$standby" op dh
  if [[ "$dir" == forward ]]; then
    pinctrl set "$in1" op dh
    pinctrl set "$in2" op dl
  else
    pinctrl set "$in1" op dl
    pinctrl set "$in2" op dh
  fi
  pinctrl set "$pwm" op dh
  sleep "$dur"
  pinctrl set "$pwm" op dl
  pinctrl set "$in1" op dl
  pinctrl set "$in2" op dl
  sleep 0.5
}

trap all_low EXIT
all_low
dump
run_motor B "$bpwm" "$bin1" "$bin2" forward 1
run_motor B "$bpwm" "$bin1" "$bin2" reverse 1
run_motor A "$apwm" "$ain1" "$ain2" forward 1
run_motor A "$apwm" "$ain1" "$ain2" reverse 1
all_low
dump
