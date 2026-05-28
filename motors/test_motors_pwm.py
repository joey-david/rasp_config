#!/usr/bin/env python3
import argparse
import signal
import sys
import time

import lgpio

STBY = 26

MOTORS = {
    "a": {"pwm": 12, "in1": 16, "in2": 6, "label": "A"},
    "b": {"pwm": 13, "in1": 20, "in2": 21, "label": "B"},
}

DEFAULT_FREQ = 1000


class Motors:
    def __init__(self, freq: int):
        self.freq = freq
        self.h = lgpio.gpiochip_open(0)
        self.closed = False
        pins = [STBY]
        for motor in MOTORS.values():
            pins.extend([motor["pwm"], motor["in1"], motor["in2"]])
        for pin in sorted(set(pins)):
            lgpio.gpio_claim_output(self.h, pin, 0)

    def stop_motor(self, name: str):
        motor = MOTORS[name]
        try:
            lgpio.tx_pwm(self.h, motor["pwm"], 0, 0)
        except Exception:
            pass
        lgpio.gpio_write(self.h, motor["in1"], 0)
        lgpio.gpio_write(self.h, motor["in2"], 0)

    def stop_all(self):
        for name in MOTORS:
            self.stop_motor(name)
        lgpio.gpio_write(self.h, STBY, 0)

    def close(self):
        if self.closed:
            return
        self.stop_all()
        lgpio.gpiochip_close(self.h)
        self.closed = True

    def run(self, name: str, direction: str, speed: float):
        motor = MOTORS[name]
        if direction == "forward":
            in1, in2 = 1, 0
        elif direction == "reverse":
            in1, in2 = 0, 1
        else:
            raise ValueError(direction)

        lgpio.gpio_write(self.h, STBY, 1)
        lgpio.gpio_write(self.h, motor["in1"], in1)
        lgpio.gpio_write(self.h, motor["in2"], in2)
        lgpio.tx_pwm(self.h, motor["pwm"], self.freq, speed)
        print(
            f"{motor['label']} {direction}: speed={speed:.1f}% freq={self.freq}Hz "
            f"STBY=GPIO{STBY} PWM=GPIO{motor['pwm']} "
            f"IN1=GPIO{motor['in1']} IN2=GPIO{motor['in2']}",
            flush=True,
        )


def parse_target(value: str):
    if "-" in value:
        motor, direction = value.split("-", 1)
    else:
        motor, direction = value, "both"
    if motor not in MOTORS and motor != "both":
        raise argparse.ArgumentTypeError("target motor must be a, b, or both")
    if direction not in ["both", "forward", "reverse"]:
        raise argparse.ArgumentTypeError("direction must be forward, reverse, or both")
    return motor, direction


def main():
    ap = argparse.ArgumentParser(description="Smooth TB6612 motor tester using lgpio PWM")
    ap.add_argument("seconds", nargs="?", type=float, default=5.0)
    ap.add_argument(
        "target",
        nargs="?",
        type=parse_target,
        default=("both", "both"),
        help="both, a, b, a-forward, a-reverse, b-forward, or b-reverse",
    )
    ap.add_argument("--speed", type=float, default=10.0, help="PWM duty percent, default 10")
    ap.add_argument("--freq", type=int, default=DEFAULT_FREQ, help="PWM frequency Hz, default 1000")
    args = ap.parse_args()
    speed = max(0.0, min(100.0, args.speed))

    motors = Motors(args.freq)

    def shutdown(signum=None, frame=None):
        print("Stopping motors", flush=True)
        motors.close()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    target_motor, target_dir = args.target
    motor_names = ["a", "b"] if target_motor == "both" else [target_motor]
    directions = ["forward", "reverse"] if target_dir == "both" else [target_dir]

    try:
        for name in motor_names:
            for direction in directions:
                motors.run(name, direction, speed)
                time.sleep(args.seconds)
                motors.stop_motor(name)
                time.sleep(0.5)
    finally:
        motors.close()


if __name__ == "__main__":
    main()
