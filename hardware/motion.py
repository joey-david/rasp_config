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
        self._last_log = 0
        self._watchdog_alive = 0.0
        self._lock = threading.RLock()
        self._stop = threading.Event()
        threading.Thread(target=self._watchdog, daemon=True).start()

    def _remember(self, left: float, right: float) -> None:
        self.left = round(clamp(left), 1)
        self.right = round(clamp(right), 1)
        self.linear = (self.left + self.right) / 2
        self.angular = (self.right - self.left) / 2
        self.speed = round(abs(self.linear), 1)
        self.direction = (
            "forward" if self.linear > 0
            else "reverse" if self.linear < 0
            else "turning" if self.left or self.right
            else "stopped"
        )
        self.turning = (
            "right" if self.angular > 0
            else "left" if self.angular < 0
            else "not"
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
        return self.tank(linear - angular, linear + angular)

    def drive_keys(self, keys: str, power: int | float | None = None) -> dict:
        """Map WASD keys directly to a motor command, with no smoothing.

        Combined keys arc-turn by mixing linear and angular commands.
        """
        ks = set(str(keys).lower())
        W, A, S, D = "w" in ks, "a" in ks, "s" in ks, "d" in ks
        y = int(W) - int(S)
        x = int(D) - int(A)

        p = max(0, min(100, int(power if power is not None else self.power)))
        self.power = p

        return self.set_velocity(y * p, x * p)

    def stop(self) -> dict:
        """Stop both motors immediately."""
        return self.tank(0, 0)

    def close(self) -> None:
        """Stop watchdog and release the motor backend."""
        self._stop.set()
        self.stop()
        self.backend.close()

    def _watchdog(self) -> None:
        """Stop the robot if no fresh command arrives within the timeout."""
        while not self._stop.is_set():
            self._watchdog_alive = time.time()
            time.sleep(0.1)

            with self._lock:
                stale = self._last_cmd and time.time() - self._last_cmd > WATCHDOG_SECONDS
                moving = self.left or self.right
                if not stale or not moving:
                    continue

            self.stop()

    def status(self) -> dict:
        """Return detailed motion and backend state."""
        with self._lock:
            return {
                "left": self.left,
                "right": self.right,
                "speed": self.speed,
                "linear": self.linear,
                "angular": self.angular,
                "direction": self.direction,
                "turning": self.turning,
                "power": self.power,
                "watchdog_alive": round(time.time() - self._watchdog_alive, 2) if self._watchdog_alive else None,
                "backend": self.backend.status(),
            }


if __name__ == "__main__":
    import argparse
    import time
    from evdev import InputDevice, ecodes, list_devices

    ap = argparse.ArgumentParser()
    ap.add_argument("--power", type=int, default=70)
    ap.add_argument("--hz", type=float, default=30)
    ap.add_argument("--device", help="evdev keyboard path, e.g. /dev/input/event3")
    args = ap.parse_args()

    def find_keyboard():
        devices = [InputDevice(p) for p in list_devices()]
        for dev in devices:
            caps = dev.capabilities().get(ecodes.EV_KEY, [])
            if ecodes.KEY_W in caps and ecodes.KEY_A in caps:
                return dev
        raise RuntimeError("No keyboard device found. Try --device /dev/input/eventX")

    dev = InputDevice(args.device) if args.device else find_keyboard()
    dev.grab()

    keymap = {
        ecodes.KEY_W: "w",
        ecodes.KEY_A: "a",
        ecodes.KEY_S: "s",
        ecodes.KEY_D: "d",
    }

    pressed = set()
    m = Motion(power_cap=args.power)

    print(f"Using {dev.path}: {dev.name}")
    print("Hold WASD to drive, space to stop, q to quit", flush=True)

    try:
        while True:
            for event in dev.read_loop():
                if event.type != ecodes.EV_KEY:
                    continue

                key = event.code
                is_down = event.value in (1, 2)  # 1=press, 2=hold
                is_up = event.value == 0

                if key == ecodes.KEY_Q and is_down:
                    raise KeyboardInterrupt

                if key == ecodes.KEY_SPACE and is_down:
                    pressed.clear()
                    m.stop()
                    continue

                if key in keymap:
                    if is_down:
                        pressed.add(keymap[key])
                    elif is_up:
                        pressed.discard(keymap[key])

                if pressed:
                    m.drive_keys("".join(pressed), args.power)
                else:
                    m.stop()

                time.sleep(1 / args.hz)

    finally:
        dev.ungrab()
        m.close()