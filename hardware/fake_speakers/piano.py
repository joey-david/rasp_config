#!/usr/bin/env python3
import argparse, select, sys, termios, time, tty
from hardware.motors import load_mapping, lgpio

NOTES = {
    "`": ("G", 392.00),
    "1": ("G#", 415.30),
    "2": ("A", 440.00),
    "3": ("A#", 466.16),
    "4": ("B", 493.88),
    "5": ("C", 523.25),
    "6": ("C#", 554.37),
    "7": ("D", 587.33),
    "8": ("D#", 622.25),
    "9": ("E", 659.25),
    "0": ("F", 698.46),
    "-": ("F#", 739.99),
    "=": ("G", 783.99),
}

ap = argparse.ArgumentParser()
ap.add_argument("--duty", type=float, default=10)
ap.add_argument("--release", type=float, default=0.18, help="seconds without repeat before note stops")
args = ap.parse_args()

cfg = load_mapping()
h = lgpio.gpiochip_open(0)
motors = [cfg["left"], cfg["right"]]
turn = 0
active = {}  # key -> {"motor": name, "last": time}

pins = {cfg["standby"]}
for m in cfg["motors"].values():
    pins |= {m["pwm"], m["in1"], m["in2"]}
for pin in pins:
    lgpio.gpio_claim_output(h, pin, 0)

def play(motor, freq):
    m = cfg["motors"][motor]
    lgpio.gpio_write(h, cfg["standby"], 1)
    lgpio.gpio_write(h, m["in1"], 1)
    lgpio.gpio_write(h, m["in2"], 0)
    lgpio.tx_pwm(h, m["pwm"], freq, args.duty)

def stop(motor):
    m = cfg["motors"][motor]
    lgpio.tx_pwm(h, m["pwm"], 0, 0)
    lgpio.gpio_write(h, m["in1"], 0)
    lgpio.gpio_write(h, m["in2"], 0)

def stop_key(k):
    if k in active:
        stop(active.pop(k)["motor"])
    if not active:
        lgpio.gpio_write(h, cfg["standby"], 0)

def stop_all():
    for k in list(active):
        stop_key(k)

old = termios.tcgetattr(sys.stdin)

try:
    tty.setcbreak(sys.stdin.fileno())
    print("SSH motor piano")
    print("1 2 3 4 5 6 7 8 9 0 - =")
    print("A A# B C C# D D# E F F# G G#")
    print("hold key = play, inferred release by timeout | space=stop | q=quit")
    print(f"duty={args.duty}% release={args.release}s")

    while True:
        now = time.time()

        ready, _, _ = select.select([sys.stdin], [], [], 0.02)
        if ready:
            k = sys.stdin.read(1)

            if k == "q":
                break
            if k == " ":
                stop_all()
                continue

            if k in NOTES:
                note, freq = NOTES[k]

                if k in active:
                    active[k]["last"] = now
                    continue

                motor = motors[turn % 2]
                turn += 1

                # one note per motor: replace whatever was on this motor
                for old_key, state in list(active.items()):
                    if state["motor"] == motor:
                        stop_key(old_key)

                play(motor, freq)
                active[k] = {"motor": motor, "last": now}
                print(f"{motor}: {note}")

        for k, state in list(active.items()):
            if now - state["last"] > args.release:
                stop_key(k)

finally:
    stop_all()
    lgpio.gpiochip_close(h)
    termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old)
