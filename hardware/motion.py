"""Layer 1 motion API: normalized movement primitives, no web/camera logic."""
import os
import threading
import time

from .motors import Motors

DEFAULT_POWER = int(os.environ.get("MOTOR_POWER", "70"))
WATCHDOG_SECONDS = float(os.environ.get("MOTOR_WATCHDOG_SECONDS", "0.35"))
MOTOR_RAMP_SECONDS = float(os.environ.get("MOTOR_RAMP_SECONDS", "0.05"))
TURN_ACCEL_SECONDS = float(os.environ.get("TURN_ACCEL_SECONDS", "1"))
TURN_MIN = float(os.environ.get("TURN_MIN", "0.2"))
TURN_MAX = float(os.environ.get("TURN_MAX", "1.0"))


def clamp(v, lo=-100.0, hi=100.0):
    return max(lo, min(hi, float(v)))


def step(v, target, amount):
    d = target - v
    return target if abs(d) <= amount else v + amount * (1 if d > 0 else -1)


class Motion:
    def __init__(self, backend: Motors | None = None):
        self.backend = backend or Motors()
        self.left = self.right = self.speed = self.target_left = self.target_right = 0.0
        self.direction = "stopped"
        self.power = max(0, min(100, DEFAULT_POWER))
        self._last_cmd = 0.0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._turn_at = time.time()
        for f in (self._ramp_worker, self._watchdog):
            threading.Thread(target=f, daemon=True).start()

    def _remember(self, left, right):
        linear = (left + right) / 2
        self.left, self.right = round(left, 1), round(right, 1)
        self.speed = round(abs(linear), 1)
        self.direction = "forward" if linear > 0 else "reverse" if linear < 0 else "turning" if left or right else "stopped"

    def tank(self, left: float, right: float):
        with self._lock:
            self.target_left, self.target_right = round(clamp(left), 1), round(clamp(right), 1)
            self._last_cmd = time.time()
        return self.status()

    def set_velocity(self, linear: float, angular: float):
        return self.tank(linear - angular, linear + angular)

    def drive_keys(self, keys: str, power: int | float | None = None):
        keys = {c for c in str(keys).lower() if c in "wasd"}
        p = max(0, min(100, int(power if power is not None else self.power)))
        y = int("w" in keys and "s" not in keys) - int("s" in keys and "w" not in keys)
        x = int("a" in keys and "d" not in keys) - int("d" in keys and "a" not in keys)
        self.power = p

        if not x:
            return self.set_velocity(y * p, 0)

        current_angular = (self.target_right - self.target_left) / 2
        base = x * p * TURN_MIN
        full = x * p * TURN_MAX
        now = time.time()
        dt = now - self._turn_at
        self._turn_at = now
        angular = base if current_angular * x <= 0 else step(current_angular, full, 100 * dt / max(TURN_ACCEL_SECONDS, dt))

        return self.set_velocity(y * p, angular)

    def stop(self):
        return self.tank(0, 0)

    def close(self):
        self._stop.set()
        self.backend.close()

    def _ramp_worker(self):
        amount = 100 * 0.01 / max(MOTOR_RAMP_SECONDS, 0.01)
        while not self._stop.is_set():
            with self._lock:
                nl = step(self.left, self.target_left, amount)
                nr = step(self.right, self.target_right, amount)
            if (nl, nr) != (self.left, self.right):
                self.backend.drive(nl, nr)
                with self._lock:
                    self._remember(nl, nr)
            time.sleep(0.01)

    def _watchdog(self):
        while not self._stop.is_set():
            time.sleep(0.1)
            with self._lock:
                stale = self._last_cmd and time.time() - self._last_cmd > WATCHDOG_SECONDS
                moving = self.target_left or self.target_right or self.left or self.right
                if stale and moving:
                    self.target_left = self.target_right = 0
                    self._last_cmd = time.time()

    def status(self) -> dict:
        return {
            "left": self.left,
            "right": self.right,
            "target_left": self.target_left,
            "target_right": self.target_right,
            "speed": self.speed,
            "direction": self.direction,
            "power": self.power,
            "backend": self.backend.status(),
        }

    def brief_status(self) -> dict:
        return {
            "left": self.left,
            "right": self.right,
            "target_left": self.target_left,
            "target_right": self.target_right,
            "speed": self.speed,
            "direction": self.direction,
            "power": self.power,
        }
