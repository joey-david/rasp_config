"""GPIO/TB6612FNG backend. Nothing above hardware.motion should import this."""
from pathlib import Path
import os

import lgpio
import yaml

# On choosing a PWM freq: https://electronics.stackexchange.com/questions/242293/is-there-an-ideal-pwm-frequency-for-dc-brush-motors
PWM_FREQ = int(os.environ.get("MOTOR_PWM_FREQ", "1000"))
ROOT = Path(__file__).resolve().parents[1]
MAPPING_FILE = Path(os.environ.get("GPIO_MAPPING_FILE", ROOT / "hardware" / "gpio_mappings.yaml"))


def load_mapping(path: Path = MAPPING_FILE) -> dict:
    raw = yaml.safe_load(path.read_text()) or {}
    left, right = raw["left_motor"], raw["right_motor"]

    motors = {
        name: {
            **{k: int(raw[name][k]) for k in ("pwm", "in1", "in2")},
            "reversed": bool(raw[name].get("reversed", name == left)),
        }
        for name in (left, right)
    }

    return {
        "driver": raw.get("motor_driver", "TB6612FNG"),
        "standby": int(raw.get("driver", {}).get("standby", 26)),
        "left": left,
        "right": right,
        "motors": motors,
        "file": str(path),
    }


class Motors:
    def __init__(self, mapping: dict | None = None):
        """Low-level motor control using lgpio and a TB6612FNG driver."""
        self.cfg = mapping or load_mapping()
        self.last = (None, None)
        # open a handle to the first gpiochip (0) 
        self.handle = lgpio.gpiochip_open(0)
        pins = [self.cfg["standby"]]
        # cycle through all motors and claim their pwm, in1, and in2 pins
        for m in self.cfg["motors"].values():
            pins += [m["pwm"], m["in1"], m["in2"]]
        # cycle through all pins and claim them as outputs, initially low
        for pin in sorted(set(pins)):
            lgpio.gpio_claim_output(self.handle, pin, 0)

    @staticmethod
    def _clamp(v):
        return max(-100.0, min(100.0, float(v)))

    def _set_one(self, name: str, speed: float):
        """Set one motor's direction pins and PWM duty cycle.

        Args:
            name: Motor key from the GPIO mapping, usually ``"left"`` or ``"right"``.
            speed: Motor command from -100.0 to 100.0.
                Positive drives forward, negative drives reverse, and 0 stops.
        """
        m = self.cfg["motors"][name]
        speed = -speed if m.get("reversed") else speed
        # if in1 high and in2 low, motor forward; if in1 low and in2 high, motor reverses; if both the same, motor stops
        in1, in2 = ((1, 0) if speed > 0 else (0, 1)) if speed else (0, 0)
        lgpio.gpio_write(self.handle, m["in1"], in1)
        lgpio.gpio_write(self.handle, m["in2"], in2)
        # lgpio already handles PWM (duty cycle) in the background, so we just need to set the desired speed as a percentage of the PWM frequency
        lgpio.tx_pwm(self.handle, m["pwm"], PWM_FREQ, abs(speed))

    def drive(self, left: float, right: float):
        """Set both motors' speeds at once, handles clamping and standby pin.
        
        Args:
            left: Left motor command from -100.0 to 100.0.
            right: Right motor command from -100.0 to 100.0.
        """
        
        left, right = round(self._clamp(left), 1), round(self._clamp(right), 1)
        if (left, right) == self.last:
            return
        # set standby high if either motor is moving, low if both are stopped
        lgpio.gpio_write(self.handle, self.cfg["standby"], int(left != 0 or right != 0))
        self._set_one(self.cfg["left"], left)
        self._set_one(self.cfg["right"], right)
        self.last = (left, right)

    def stop(self):
        """Stop both motors immediately."""
        self.drive(0, 0)

    def close(self):
        """Stop motors and release GPIO pins."""
        self.stop()
        if self.handle is not None:
            lgpio.gpiochip_close(self.handle)
            self.handle = None

    def status(self) -> dict:
        """Return current motor status for debugging."""
        return {"backend": "lgpio", "mapping": self.cfg, "last": self.last}