"""Central robot facade. Web and skills call this, not hardware directly."""

import time
import math

from hardware.motion import Motion
from hardware.safety.safety import enforce as enforce_safety, status as safety_status
from perception.camera import Camera
from perception.odometry.runtime import RobotOdometry
from perception.remote import RemotePerception
from perception.vision import VisionScanner
from skills import emotes
from skills.objects import ObjectSkills

TURNING_SPEED_BUILDUP = 2


class SkillMovement:
    """Reusable motion policy helpers for skills."""

    def __init__(self, robot):
        self.robot = robot

    @staticmethod
    def clamp(x, lo, hi):
        return max(lo, min(hi, float(x)))

    def turn(self, err, kp, deadband, stop_deadband, min_turn, max_turn):
        cmd = kp * err
        if abs(err) <= stop_deadband:
            return 0.0
        if abs(cmd) < min_turn:
            span = max(0.001, deadband - stop_deadband)
            boost = self.clamp((abs(err) - stop_deadband) / span, 0.0, 1.0)
            floor = min_turn * boost
            if abs(cmd) < floor:
                cmd = floor if (cmd or err) > 0 else -floor
        return self.clamp(cmd, -max_turn, max_turn)

    def with_stuck_bonus(self, turn, err, bonus, max_turn):
        if not turn or not bonus:
            return turn
        return self.clamp(turn + (bonus if err > 0 else -bonus), -max_turn, max_turn)

    def set_velocity(self, linear, angular, seq=None, source="skill"):
        return self.robot.set_velocity(linear, angular, seq=seq, source=source)

    def stop(self, seq=None, source="skill"):
        return self.robot.stop(seq=seq, source=source)

    def rotation_rad_s(self):
        return self.robot.odometry.rotation_rad_s()

    def set_rotation_target(self, rad_s):
        return self.robot.odometry.set_rotation_target(rad_s)


class RobotAPI:
    def __init__(self):
        self.camera = Camera()
        self.motion = Motion()
        self.perception = RemotePerception()
        self.vision = VisionScanner(self)
        self.odometry = RobotOdometry(self)
        self.skills = ObjectSkills(self)
        self.movement = SkillMovement(self)
        self.control = {"mode": "idle", "keys": "", "source": "none"}
        self._status_cache = {}
        self._status_at = 0.0
        self._status_ttl = 0.1
        self._last_motion_seq = -1
        self.key_turn_target = 0

    @property
    def direction(self):
        return self.motion.direction

    @property
    def speed(self):
        return self.motion.speed

    def start(self):
        self.camera.start()
        self.vision.start()

    def close(self):
        self.stop()
        self.vision.stop()
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
        self.control = {
            "mode": "manual" if clean else "idle",
            "keys": clean,
            "source": "web",
        }

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
        self.motion.tank(left, right)
        enforce_safety(self)
        return self.drive_status()

    def set_velocity(self, linear, angular, seq=None, source="layer2"):
        if not self._fresh_motion_seq(seq):
            return self.drive_status(stale=True)
        self.control = {"mode": "auto", "keys": "", "source": source}
        self._status_at = 0.0
        out = self.motion.set_velocity(linear, angular)
        enforce_safety(self)
        return out

    def snapshot(self):
        return self.camera.snapshot()

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
            "seq": self._last_motion_seq,
        }

    #
    def resolve_object(self, query, prefer_visible=True):
        from mischief_common.filters import is_environmental

        if is_environmental(query):
            return None
        return self.perception.best(query)

    def goto(self, target):
        return self.skills.goto(target)

    def find(self, target):
        return self.skills.find_odometric(target)

    def push(self, target):
        return self.skills.push(target)

    def emote(self, name, scale=1.0):
        return emotes.run(self, name, scale)

    def status(self, force=False):
        now = time.time()
        if (
            not force
            and self._status_cache
            and now - self._status_at <= self._status_ttl
        ):
            return self._status_cache
        motion = self.motion.status()
        safety = safety_status()
        self._status_cache = {
            "motion": motion,
            "camera": self.camera.status(),
            "perception": self.perception.status(),
            "odometry": self.odometry.status(),
            "safety": safety,
            "layers": {
                "level3": {
                    "mode": "pc-perception",
                    "source": self.perception.receiver.last_packet.get(
                        "source", "none"
                    ),
                },
                "level2": self.skills.status()["layer2"],
                "level1": motion,
                "level0": safety,
            },
            "control": self.control,
        }
        self._status_at = now
        return self._status_cache


try:
    robot = RobotAPI()
except Exception as e:
    import sys

    if "GPIO busy" in str(e) or "busy" in str(e).lower():
        print("GPIO busy — service already running. Stop it first:", file=sys.stderr)
        print("  sudo systemctl stop mischief-bot.service", file=sys.stderr)
        sys.exit(1)
    raise
