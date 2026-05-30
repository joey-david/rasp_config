"""Layer 1 motion API: normalized movement primitives, no web/camera logic."""
import os
import threading
import time
from .motors import Motors

DEFAULT_POWER = int(os.environ.get("MOTOR_POWER", "50"))
WATCHDOG_SECONDS = float(os.environ.get("MOTOR_WATCHDOG_SECONDS", "0.35"))


def clamp(v, lo=-100.0, hi=100.0):
    return max(lo, min(hi, float(v)))


class Motion:
    def __init__(self, backend: Motors | None = None):
        self.backend = backend or Motors()
        self.left = self.right = self.speed = 0.0
        self.direction = "stopped"
        self.power = max(0, min(100, DEFAULT_POWER))
        self._last_cmd = 0.0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        threading.Thread(target=self._watchdog, daemon=True).start()

    # keep inventory of commands for debugging
    def _remember(self, left, right):
        linear = (left + right) / 2
        self.left, self.right = left, right
        self.speed = round(abs(linear), 1)
        self.direction = "forward" if linear > 0 else "reverse" if linear < 0 else "turning" if left or right else "stopped"
        self._last_cmd = time.time()

    # directly command left/right motors
    def tank(self, left: float, right: float):
        left, right = round(clamp(left), 1), round(clamp(right), 1)
        with self._lock:
            self.backend.drive(left, right)
            self._remember(left, right)
        return self.status()

    def set_velocity(self, linear: float, angular: float):
        return self.tank(clamp(linear - angular), clamp(linear + angular))

    def drive_keys(self, keys: str, power: int | float | None = None):
        keys = {c for c in str(keys).lower() if c in "wasd"}
        p = max(0, min(100, int(power if power is not None else self.power)))
        y = int("w" in keys and "s" not in keys) - int("s" in keys and "w" not in keys)
        x = int("d" in keys and "a" not in keys) - int("a" in keys and "d" not in keys)
        self.power = p
        return self.tank((y + x) * p, (y - x) * p)

    def stop(self):
        return self.tank(0, 0)

    def close(self):
        self._stop.set()
        self.backend.close()

    # stops robot if control/connection is lost
    def _watchdog(self):
        while not self._stop.is_set():
            time.sleep(0.1)
            with self._lock:
                stale = self._last_cmd and time.time() - self._last_cmd > WATCHDOG_SECONDS and (self.left or self.right)
            if stale:
                self.stop()

    def status(self) -> dict:
        return {
            "left": self.left,
            "right": self.right,
            "speed": self.speed,
            "direction": self.direction,
            "power": self.power,
            "backend": self.backend.status(),
        }
