"""Central robot facade. Web, skills, and reasoning call this, not hardware directly."""
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
        self.perception = RemotePerception(self.memory)
        self.skills = ObjectSkills(self)
        self.control = {"mode": "idle", "keys": "", "source": "none"}

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
        return self.motion.stop()

    def drive_keys(self, keys, power=None):
        clean = "".join(c for c in str(keys).lower() if c in "wasd")
        self.control = {"mode": "manual" if clean else "idle", "keys": clean, "source": "web"}
        self.motion.drive_keys(keys, power); enforce_safety(self); return self.status()

    def drive_tank(self, left, right):
        self.control = {"mode": "manual", "keys": "", "source": "tank"}
        self.motion.tank(left, right); enforce_safety(self); return self.status()

    def set_velocity(self, linear, angular):
        self.control = {"mode": "auto", "keys": "", "source": "layer2"}
        out = self.motion.set_velocity(linear, angular); enforce_safety(self); return out

    def snapshot(self): return self.camera.snapshot()

    def ingest_detections(self, payload): return self.perception.ingest(payload)

    def resolve_object(self, query, prefer_visible=True):
        visible = self.perception.latest if self.perception.is_fresh() else []
        return self.memory.resolve(query, visible, prefer_visible)

    def goto(self, target): return self.skills.goto(target)

    def push(self, target): return self.skills.push(target)

    def status(self):
        return {
            "motion": self.motion.status(),
            "camera": self.camera.status(),
            "perception": self.perception.status(),
            "memory": {"inventory": self.memory.inventory()},
            "safety": safety_status(),
            "layers": self.skills.status(),
            "control": self.control,
        }

robot = RobotAPI()
