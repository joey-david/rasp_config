#!/usr/bin/env python3
import argparse, os, signal, subprocess, time
from hardware.motors import load_mapping, lgpio

ap = argparse.ArgumentParser()
ap.add_argument("file")
ap.add_argument("--motor", choices=["left", "right", "both"], default="both")
ap.add_argument("--volume", type=float, default=18, help="max duty percent")
ap.add_argument("--rate", type=int, default=4000, help="audio sample rate")
ap.add_argument("--carrier", type=int, default=20000, help="PWM carrier Hz")
args = ap.parse_args()

cfg = load_mapping()
h = lgpio.gpiochip_open(0)

names = []
if args.motor in ("left", "both"):
    names.append(cfg["left"])
if args.motor in ("right", "both"):
    names.append(cfg["right"])

pins = {cfg["standby"]}
for m in cfg["motors"].values():
    pins |= {m["pwm"], m["in1"], m["in2"]}
for p in pins:
    lgpio.gpio_claim_output(h, p, 0)

def drive(name, x):
    m = cfg["motors"][name]
    duty = min(args.volume, abs(x) * args.volume)

    if duty < 1:
        lgpio.tx_pwm(h, m["pwm"], args.carrier, 0)
        return

    if x >= 0:
        lgpio.gpio_write(h, m["in1"], 1)
        lgpio.gpio_write(h, m["in2"], 0)
    else:
        lgpio.gpio_write(h, m["in1"], 0)
        lgpio.gpio_write(h, m["in2"], 1)

    lgpio.tx_pwm(h, m["pwm"], args.carrier, duty)

def stop_all():
    for m in cfg["motors"].values():
        lgpio.tx_pwm(h, m["pwm"], args.carrier, 0)
        lgpio.gpio_write(h, m["in1"], 0)
        lgpio.gpio_write(h, m["in2"], 0)
    lgpio.gpio_write(h, cfg["standby"], 0)

cmd = [
    "ffmpeg", "-hide_banner", "-loglevel", "error",
    "-i", args.file,
    "-ac", "1",
    "-ar", str(args.rate),
    "-f", "u8",
    "pipe:1",
]

proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, preexec_fn=os.setsid)
dt = 1 / args.rate
next_t = time.perf_counter()

print(f"playing {args.file}")
print(f"motor={args.motor} volume={args.volume}% rate={args.rate}Hz carrier={args.carrier}Hz")
print("ctrl+c to stop")

try:
    lgpio.gpio_write(h, cfg["standby"], 1)

    while True:
        b = proc.stdout.read(1)
        if not b:
            break

        # unsigned 8-bit PCM: 128 is center/silence.
        x = (b[0] - 128) / 128.0

        for name in names:
            drive(name, x)

        next_t += dt
        sleep = next_t - time.perf_counter()
        if sleep > 0:
            time.sleep(sleep)

except KeyboardInterrupt:
    pass

finally:
    stop_all()
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except Exception:
        pass
    lgpio.gpiochip_close(h)
    print("\nstopped")
