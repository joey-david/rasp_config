"""Central robot facade. Web and skills call this, not hardware directly."""
import time
import math

from hardware.motion import Motion
from hardware.safety.safety import enforce as enforce_safety, status as safety_status
from perception.camera import Camera
from perception.remote import RemotePerception
from skills.objects import ObjectSkills

TURNING_SPEED_BUILDUP = 2

class RobotAPI:
    def __init__(self):
        self.camera = Camera()
        self.motion = Motion()
        self.perception = RemotePerception()
        self.skills = ObjectSkills(self)
        self.control = {"mode": "idle", "keys": "", "source": "none"}
        self._status_cache = {}
        self._status_at = 0.0
        self._status_ttl = 0.1
        self._last_motion_seq = -1
        self.key_turn_target = 0
        
    @property
    def direction(self): return self.motion.direction

    @property
    def speed(self): return self.motion.speed

    def start(self):
        self.camera.start()
        self.perception.start()

    def close(self):
        self.stop()
        self.perception.stop()
        self.camera.stop()
        self.motion.close()

    def _fresh_motion_seq(self, seq):
        try:
            seq = int(seq)
        except Exception:
            return True
        if seq <= self._last_motion_seq:
            return False
        self._last_motion_seq = seq
        return True

    def stop(self, seq=None, source="stop"):
        if not self._fresh_motion_seq(seq):
            return self.drive_status(stale=True)
        self.control = {"mode": "idle", "keys": "", "source": source}
        self.key_turn_target = 0
        self._status_at = 0.0
        return self.motion.stop()


    # see video/script/curve_turn_tweak.png for new logic
    def drive_keys(self, keys, power=None, seq=None):
        if not self._fresh_motion_seq(seq):
            return self.drive_status(stale=True)

        clean = "".join(c for c in str(keys).lower() if c in "wasd")
        self.control = {"mode": "manual" if clean else "idle", "keys": clean, "source": "web"}

        p = max(0, min(100, int(power if power is not None else self.motion.power)))
        y = int("w" in clean) - int("s" in clean)

        turn_log = 0.3  # 0 = linear, 1 = full turn immediately
        turn_log = max(0.0, min(1.0, turn_log))

        step = TURNING_SPEED_BUILDUP * (2 if y == 0 else 1)

        if "d" in clean:
            if self.key_turn_target >= 0:
                self.key_turn_target = min(100, self.key_turn_target + step)
            else:
                self.key_turn_target = step

        elif "a" in clean:
            if self.key_turn_target <= 0:
                self.key_turn_target = max(-100, self.key_turn_target - step)
            else:
                self.key_turn_target = -step

        else:
            self.key_turn_target = 0

        x = abs(self.key_turn_target) / 100.0

        if x == 0:
            turn = 0
        elif turn_log >= 1:
            turn = 100
        elif turn_log <= 0:
            turn = self.key_turn_target
        else:
            k = turn_log / (1.0 - turn_log)
            curved = math.log1p(k * x) / math.log1p(k)
            turn = math.copysign(curved * 100, self.key_turn_target)

        self.motion.set_velocity(y * p, turn)
        enforce_safety(self)
        return self.drive_status()

    def drive_tank(self, left, right, seq=None, source="tank"):
        if not self._fresh_motion_seq(seq):
            return self.drive_status(stale=True)
        self.control = {"mode": "manual", "keys": "", "source": source}
        self.motion.tank(left, right); enforce_safety(self); return self.drive_status()

    def set_velocity(self, linear, angular, seq=None, source="layer2"):
        if not self._fresh_motion_seq(seq):
            return self.drive_status(stale=True)
        self.control = {"mode": "auto", "keys": "", "source": source}
        self._status_at = 0.0
        out = self.motion.set_velocity(linear, angular); enforce_safety(self); return out

    def snapshot(self): return self.camera.snapshot()

    def ingest_detections(self, payload):
        self._status_at = 0.0
        return self.perception.ingest(payload)

    def drive_status(self, stale=False):
        self._status_at = 0.0
        return {
            "motion": self.motion.status(),
            "control": self.control,
            "safety": safety_status(),
            "stale": stale,
        }

    def resolve_object(self, query, prefer_visible=True):
        from mischief_common.filters import is_environmental
        if is_environmental(query):
            return None
        return self.perception.best(query)

    def goto(self, target): return self.skills.goto(target)

    def push(self, target): return self.skills.push(target)

    def status(self, force=False):
        now = time.time()
        if not force and self._status_cache and now - self._status_at <= self._status_ttl:
            return self._status_cache
        motion = self.motion.status()
        safety = safety_status()
        self._status_cache = {
            "motion": motion,
            "camera": self.camera.status(),
            "perception": self.perception.status(),
            "safety": safety,
            "turbo": _turbo,
            "layers": {
                "level3": {"mode": "pc-perception", "source": self.perception.receiver.last_packet.get("source", "none")},
                "level2": self.skills.status()["layer2"],
                "level1": motion,
                "level0": safety,
            },
            "control": self.control,
        }
        self._status_at = now
        return self._status_cache


_turbo = False


def turbo(on: bool) -> dict:
    """Performance mode: 30fps camera, no perception, pure WASD driving."""
    global _turbo
    if on == _turbo:
        return {"turbo": _turbo, "changed": False}
    _turbo = on
    if on:
        robot.camera.apply_settings(fps=30)
        robot.perception.stop()
    else:
        robot.camera.apply_settings(fps=15)
        robot.perception.start()
    return {"turbo": _turbo, "changed": True}

try:
    robot = RobotAPI()
except Exception as e:
    import sys
    if "GPIO busy" in str(e) or "busy" in str(e).lower():
        print("GPIO busy — service already running. Stop it first:", file=sys.stderr)
        print("  sudo systemctl stop mischief-bot.service", file=sys.stderr)
        sys.exit(1)
    raise
