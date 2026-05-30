"""Central robot facade. Web, skills, and reasoning call this, not hardware directly."""
from hardware.motion import Motion
from hardware.safety.safety import enforce as enforce_safety
from perception.camera import Camera
from perception.detection import Detector
from memory.object_memory import ObjectMemory
from skills.objects import ObjectSkills


class RobotAPI:
    def __init__(self):
        self.camera = Camera()
        self.motion = Motion()
        self.memory = ObjectMemory()
        self.perception = Detector(self.camera, self.memory)
        self.skills = ObjectSkills(self)

    @property
    def direction(self): return self.motion.direction

    @property
    def speed(self): return self.motion.speed

    def start(self):
        self.camera.start()
        self.perception.start()

    def close(self):
        self.stop(); self.perception.stop(); self.camera.stop(); self.motion.close()

    def stop(self): return self.motion.stop()

    def drive_keys(self, keys, power=None):
        self.motion.drive_keys(keys, power); enforce_safety(self); return self.status()

    def drive_tank(self, left, right):
        self.motion.tank(left, right); enforce_safety(self); return self.status()

    def set_velocity(self, linear, angular):
        out = self.motion.set_velocity(linear, angular); enforce_safety(self); return out

    def snapshot(self): return self.camera.snapshot()

    def resolve_object(self, query, prefer_visible=True):
        return self.memory.resolve(query, self.perception.latest, prefer_visible)

    def goto(self, target): return self.skills.goto(target)

    def push(self, target): return self.skills.push(target)

    def status(self):
        return {
            "motion": self.motion.status(),
            "camera": self.camera.status(),
            "perception": self.perception.status(),
            "memory": {"inventory": self.memory.inventory()},
        }


robot = RobotAPI()
