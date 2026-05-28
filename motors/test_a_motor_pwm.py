#!/usr/bin/env python3
import argparse
import signal
import sys
import time

import lgpio

STBY = 26  # physical pin 37
APWM = 12  # physical pin 32
AIN1 = 16  # physical pin 36
AIN2 = 6   # physical pin 31
DEFAULT_FREQ = 1000
PINS = [STBY, APWM, AIN1, AIN2]


class MotorA:
    def __init__(self, freq: int):
        self.freq = freq
        self.h = lgpio.gpiochip_open(0)
        self.closed = False
        for pin in PINS:
            lgpio.gpio_claim_output(self.h, pin, 0)

    def stop(self):
        try:
            lgpio.tx_pwm(self.h, APWM, 0, 0)
        except Exception:
            pass
        for pin in PINS:
            try:
                lgpio.gpio_write(self.h, pin, 0)
            except Exception:
                pass

    def close(self):
        if self.closed:
            return
        self.stop()
        lgpio.gpiochip_close(self.h)
        self.closed = True

    def run(self, direction: str, speed: float):
        if direction == "forward":
            in1, in2 = 1, 0
        elif direction == "reverse":
            in1, in2 = 0, 1
        else:
            raise ValueError(direction)

        lgpio.gpio_write(self.h, STBY, 1)
        lgpio.gpio_write(self.h, AIN1, in1)
        lgpio.gpio_write(self.h, AIN2, in2)
        lgpio.tx_pwm(self.h, APWM, self.freq, speed)
        print(
            f"A {direction}: speed={speed:.1f}% freq={self.freq}Hz "
            f"STBY=GPIO{STBY} APWM=GPIO{APWM} AIN1=GPIO{AIN1} AIN2=GPIO{AIN2}",
            flush=True,
        )


def main():
    ap = argparse.ArgumentParser(description="Smooth Motor A tester using lgpio PWM")
    ap.add_argument("seconds", nargs="?", type=float, default=5.0)
    ap.add_argument(
        "mode",
        nargs="?",
        choices=["both", "forward", "reverse", "hold-forward", "hold-reverse"],
        default="both",
    )
    ap.add_argument("--speed", type=float, default=10.0, help="PWM duty percent, default 10")
    ap.add_argument("--freq", type=int, default=DEFAULT_FREQ, help="PWM frequency Hz, default 1000")
    args = ap.parse_args()
    speed = max(0.0, min(100.0, args.speed))

    motor = MotorA(args.freq)

    def shutdown(signum=None, frame=None):
        print("Stopping motor A", flush=True)
        motor.close()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        if args.mode == "both":
            motor.run("forward", speed)
            time.sleep(args.seconds)
            motor.stop()
            time.sleep(0.5)
            motor.run("reverse", speed)
            time.sleep(args.seconds)
        elif args.mode == "forward":
            motor.run("forward", speed)
            time.sleep(args.seconds)
        elif args.mode == "reverse":
            motor.run("reverse", speed)
            time.sleep(args.seconds)
        elif args.mode == "hold-forward":
            motor.run("forward", speed)
            while True:
                time.sleep(5)
        elif args.mode == "hold-reverse":
            motor.run("reverse", speed)
            while True:
                time.sleep(5)
    finally:
        motor.close()


if __name__ == "__main__":
    main()
