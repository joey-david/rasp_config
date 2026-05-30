"""GPIO/TB6612FNG backend. Nothing above hardware.motion should import this."""
from pathlib import Path
import os
import lgpio
import yaml

PWM_FREQ = int(os.environ.get("MOTOR_PWM_FREQ", "1000")) # spliting of the motor powering, high value to avoid chopped movement
ROOT = Path(__file__).resolve().parents[1]
MAPPING_FILE = Path(os.environ.get("GPIO_MAPPING_FILE", ROOT / "hardware" / "gpio_mappings.yaml")) #get the gpio config

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
        self.cfg = mapping or load_mapping()
        self.last = (None, None)
        self.h = lgpio.gpiochip_open(0)
        pins = [self.cfg["standby"]]
        for m in self.cfg["motors"].values():
            pins += [m["pwm"], m["in1"], m["in2"]]
        for pin in sorted(set(pins)):
            lgpio.gpio_claim_output(self.h, pin, 0)

    @staticmethod
    def _clamp(v):
        return max(-100.0, min(100.0, float(v)))

    # set a speed for one of the motors
    def _set_one(self, name: str, speed: float):
        m = self.cfg["motors"][name]
        speed = -speed if m.get("reversed") else speed
        in1, in2 = ((1, 0) if speed > 0 else (0, 1)) if speed else (0, 0)
        lgpio.gpio_write(self.h, m["in1"], in1)
        lgpio.gpio_write(self.h, m["in2"], in2)
        lgpio.tx_pwm(self.h, m["pwm"], PWM_FREQ, abs(speed))


    def drive(self, left: float, right: float):
        left, right = round(self._clamp(left), 1), round(self._clamp(right), 1)
        # if nothing's changed, no need to start new writes
        if (left, right) == self.last:
            return
        lgpio.gpio_write(self.h, self.cfg["standby"], int(left != 0 or right != 0))
        self._set_one(self.cfg["left"], left)
        self._set_one(self.cfg["right"], right)
        self.last = (left, right)

    def stop(self):
        self.drive(0, 0)

    def close(self):
        self.stop()
        if self.h is not None:
            lgpio.gpiochip_close(self.h)
            self.h = None

    def status(self) -> dict:
        return {"backend": "lgpio", "mapping": self.cfg, "last": self.last}
