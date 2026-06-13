"""Layer 1 motion API: normalized movement primitives, no web/camera logic."""

import os
import argparse
import select
import threading
import time
import sys
import termios
import tty

try:
    from .motors import Motors
except ImportError:  # pragma: no cover - direct script execution
    from motors import Motors

WATCHDOG_SECONDS = float(os.environ.get("MOTOR_WATCHDOG_SECONDS", "1.0"))
RELEASE_IDLE_SECONDS = float(os.environ.get("MOTOR_RELEASE_IDLE_SECONDS", "5.0"))


def clamp(v: float, lo: float = -100.0, hi: float = 100.0) -> float:
    """Clamp a numeric motor command into the safe normalized range."""
    return max(lo, min(hi, float(v)))


class Motion:
    """Immediate normalized motion API.

    This layer intentionally does not do acceleration ramps, turn smoothing,
    camera logic, or behavior-specific motion policy. Callers decide what
    commands to send; this class only clamps them, sends them to the motor
    backend, remembers state, and stops stale commands through a watchdog.
    """

    def __init__(self, backend: Motors | None = None, power_cap: float = 100.0):
        self.backend = backend or Motors()

        self.left = 0.0
        self.right = 0.0
        self.speed = 0.0
        self.linear = 0.0
        self.angular = 0.0
        self.direction = "stopped"
        self.turning = "not"
        self.power = max(0.0, min(100.0, float(power_cap)))

        # last command time for watchdog, and last log time for status changes
        self._last_cmd = time.time()
        self._watchdog_alive = 0.0
        self._idle_since = time.time()
        self._lock = threading.RLock()
        self._stop = threading.Event()
        threading.Thread(target=self._watchdog, daemon=True).start()

    def _remember(self, left: float, right: float) -> None:
        self.left = round(clamp(left), 1)
        self.right = round(clamp(right), 1)
        self.linear = (self.left + self.right) / 2
        self.angular = (self.left - self.right) / 2
        self.speed = round(abs(self.linear), 1)
        self.direction = (
            "forward"
            if self.linear > 0
            else "reverse"
            if self.linear < 0
            else "turning"
            if self.left or self.right
            else "stopped"
        )
        self.turning = (
            "right" if self.angular > 0 else "left" if self.angular < 0 else "not"
        )
        self._idle_since = (
            None if (self.left or self.right) else self._idle_since or time.time()
        )

    def tank(self, left: float, right: float) -> dict:
        """Drive the left and right motors immediately.

        Args:
            left: Left motor command from -100.0 to 100.0.
            right: Right motor command from -100.0 to 100.0.

        Returns:
            Current motion status.
        """
        left = round(clamp(left), 1)
        right = round(clamp(right), 1)

        with self._lock:
            self._last_cmd = time.time()
            if left or right or self.left or self.right:
                try:
                    self.backend.drive(left, right)
                except Exception as e:
                    print(f"[motion] drive error: {e}", flush=True)
                    self.backend.last = (None, None)  # force backend retry next time
                    raise
            self._remember(left, right)
        return self.status()

    def set_velocity(self, linear: float, angular: float) -> dict:
        """Drive using normalized linear/angular commands.

        Args:
            linear: Forward/reverse command from -100.0 to 100.0.
            angular: Turn command from -100.0 to 100.0.
                Positive turns right, negative turns left.
        """
        return self.tank(linear + angular, linear - angular)

    def stop(self) -> dict:
        """Stop both motors immediately."""
        return self.tank(0, 0)

    def close(self) -> None:
        """Stop watchdog and release the motor backend."""
        self._stop.set()
        with self._lock:
            if self.left or self.right:
                self.backend.drive(0, 0)
            self._remember(0, 0)
            self.backend.close()

    def release(self) -> None:
        """Release GPIO after the motors are already stopped."""
        with self._lock:
            if not (self.left or self.right):
                self.backend.close()

    def _watchdog(self) -> None:
        """Stop the robot if no fresh command arrives within the timeout."""
        while not self._stop.is_set():
            self._watchdog_alive = time.time()
            time.sleep(0.1)

            with self._lock:
                stale = (
                    self._last_cmd and time.time() - self._last_cmd > WATCHDOG_SECONDS
                )
                moving = self.left or self.right
                idle_release = (
                    RELEASE_IDLE_SECONDS > 0
                    and self._idle_since
                    and time.time() - self._idle_since > RELEASE_IDLE_SECONDS
                )
                if idle_release:
                    self.backend.close()
                    self._idle_since = time.time()
                if not stale or not moving:
                    continue

            self.stop()

    def status(self) -> dict:
        """Return detailed motion and backend state."""
        with self._lock:
            backend = self.backend.status()
            return {
                "left": self.left,
                "right": self.right,
                "speed": self.speed,
                "linear": self.linear,
                "angular": self.angular,
                "direction": self.direction,
                "turning": self.turning,
                "power": self.power,
                "released": not backend.get("claimed", True),
                "watchdog_alive": round(time.time() - self._watchdog_alive, 2)
                if self._watchdog_alive
                else None,
                "backend": backend,
            }


if __name__ == "__main__":
    # simple test script to verify motors are working, and demonstrate usage of the Motion API
    motion = Motion()
    try:
        print("Driving forward...")
        for i in range(10):
            motion.set_velocity(50, 0)
            time.sleep(0.1)

        print("Driving reverse...")
        for i in range(10):
            motion.set_velocity(-50, 0)
            time.sleep(0.1)

        print("Turning right...")
        for i in range(10):
            motion.set_velocity(0, 50)
            time.sleep(0.1)

        print("Turning left...")
        for i in range(10):
            motion.set_velocity(0, -50)
            time.sleep(0.1)

        print("Stopping...")
        motion.stop()
    finally:
        motion.close()
