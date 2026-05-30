"""Central robot facade. Web, skills, and reasoning call this, not hardware directly."""
from hardware.motion import Motion
from hardware.safety.safety import enforce as enforce_safety
from perception.camera import Camera


class RobotAPI:
    def __init__(self):
        self.camera = Camera()
        self.motion = Motion()

    @property
    def direction(self):
        return self.motion.direction

    @property
    def speed(self):
        return self.motion.speed

    def start(self):
        self.camera.start()

    def close(self):
        self.stop()
        self.camera.stop()
        self.motion.close()

    def stop(self):
        return self.motion.stop()

    def drive_keys(self, keys, power=None):
        out = self.motion.drive_keys(keys, power)
        enforce_safety(self)
        return out

    def drive_tank(self, left, right):
        out = self.motion.tank(left, right)
        enforce_safety(self)
        return out

    def set_velocity(self, linear, angular):
        out = self.motion.set_velocity(linear, angular)
        enforce_safety(self)
        return out

    def snapshot(self):
        return self.camera.snapshot()

    def status(self):
        return {"motion": self.motion.status(), "camera": self.camera.status()}


robot = RobotAPI()
