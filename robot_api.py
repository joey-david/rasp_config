"""Central robot facade. Web, skills, and reasoning call this, not hardware directly."""
import time

from hardware.motion import Motion
from hardware.safety.safety import enforce as enforce_safety, status as safety_status
from perception.camera import Camera
from perception.remote import RemotePerception
from memory.object_memory import ObjectMemory
from skills.objects import ObjectSkills


class RobotAPI:
    def __init__(self):
        self.camera = Camera()
        self.motion = Motion()
        self.memory = ObjectMemory()
        self.perception = RemotePerception(self.memory, self.camera, self.motion)
        self.skills = ObjectSkills(self)
        self.control = {"mode": "idle", "keys": "", "source": "none"}
        self._status_cache = {}
        self._status_at = 0.0
        self._status_ttl = 0.1
        self._last_drive_seq = -1

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

    def stop(self):
        self.control = {"mode": "idle", "keys": "", "source": "stop"}
        self._status_at = 0.0
        return self.motion.stop()

    def drive_keys(self, keys, power=None, seq=None):
        try:
            seq = int(seq)
        except Exception:
            seq = None
        if seq is not None and seq < self._last_drive_seq:
            return self.drive_status(stale=True)
        if seq is not None:
            self._last_drive_seq = seq
        clean = "".join(c for c in str(keys).lower() if c in "wasd")
        self.control = {"mode": "manual" if clean else "idle", "keys": clean, "source": "web"}
        self.motion.drive_keys(keys, power); enforce_safety(self); return self.drive_status()

    def drive_tank(self, left, right):
        self.control = {"mode": "manual", "keys": "", "source": "tank"}
        self.motion.tank(left, right); enforce_safety(self); return self.drive_status()

    def set_velocity(self, linear, angular):
        self.control = {"mode": "auto", "keys": "", "source": "layer2"}
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
        return self.perception.best(query) or self.memory.resolve(query, [], prefer_visible)

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
            "memory": {"inventory": self.memory.inventory()},
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
