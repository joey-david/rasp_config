"""Central robot facade. Web and skills call this, not hardware directly."""

import time
import math

from autonomy import AutonomyController
from hardware.ownership import MotionOwner, owned_write
from hardware.motion import Motion
from hardware.safety.safety import (
    command_allowed,
    reset as reset_safety,
    start as start_safety,
    status as safety_status,
    stop as stop_safety,
)
from perception.camera import Camera
from perception.odometry.runtime import RobotOdometry
from perception.remote import RemotePerception
from perception.spatial_map import SpatialMap
from perception.vision import VisionScanner
from skills.runtime import centering_turn
from skills import emotes
from skills import find as find_skill
from skills import follow as follow_skill
from skills.objects import ObjectSkills
from skills.power_gauge import PowerGauge
from skills.tuning import FORWARD_MAX, TURN_MAX

TURNING_SPEED_BUILDUP = 2


class SkillMovement:
    """Reusable motion policy helpers for skills."""

    def __init__(self, robot):
        self.robot = robot

    @staticmethod
    def clamp(x, lo, hi):
        return max(lo, min(hi, float(x)))

    def turn(self, err, kp, deadband, stop_deadband, min_turn, max_turn):
        if abs(err) <= max(deadband, stop_deadband):
            return 0.0
        return centering_turn(err, min_turn, max_turn)

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

    def turn_bounds(self, default_max=TURN_MAX):
        return self.robot.power_gauge.turn_bounds(
            default_max=default_max, power_cap=self.robot.motion.power
        )

    def forward_bounds(self, default_max=FORWARD_MAX):
        return self.robot.power_gauge.forward_bounds(
            default_max=default_max, power_cap=self.robot.motion.power
        )


class RobotAPI:
    def __init__(self):
        self.owner = MotionOwner()
        self.camera = Camera()
        self.spatial_map = SpatialMap()
        self.motion = Motion(observer=self.spatial_map.command)
        self.perception = RemotePerception()
        self.vision = VisionScanner(self)
        self.odometry = RobotOdometry(self)
        self.power_gauge = PowerGauge()
        self.skills = ObjectSkills(self)
        self.movement = SkillMovement(self)
        self.autonomy = AutonomyController(self)
        self.control = {"mode": "idle", "keys": "", "source": "none"}
        # Replaced by the web server with its skill registry; Level 0 learns its
        # edge baseline only while no skill is active.
        self.skill_active = lambda: bool(self.skills.current.get("running"))
        self._status_cache = {}
        self._status_at = 0.0
        self._status_ttl = 0.1
        self._last_motion_seq = -1
        self._last_trace_command = None
        self.key_turn_target = 0

    @property
    def direction(self):
        return self.motion.direction

    @property
    def speed(self):
        return self.motion.speed

    def start(self):
        self.camera.start()
        print("[perception] camera stream starting", flush=True)
        start_safety(self)
        self.vision.start()
        print(f"[perception] scanner started at {self.vision.hz:g} Hz", flush=True)

    def close(self):
        self.autonomy.stop()
        self.stop()
        self.vision.stop()
        stop_safety()
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

    @owned_write
    def stop(self, seq=None, source="stop"):
        self._fresh_motion_seq(seq)
        self.control = {"mode": "idle", "keys": "", "source": source}
        self.key_turn_target = 0
        self._status_at = 0.0
        was_moving = bool(self.motion.left or self.motion.right)
        out = self.motion.stop()
        if was_moving:
            self._last_trace_command = None
        if was_moving and source not in {"web", "http"}:
            print(f"[level1] stop source={source}", flush=True)
        return out

    def operator_stop(self, seq=None, source="stop"):
        with self.owner.lock:
            self.owner.revoke()
            return self.stop(seq=seq, source=source)

    def _safety_stop(self):
        out = self.motion.stop()
        self._last_trace_command = None
        return out

    def _velocity(self, linear, angular, source="unknown"):
        if not command_allowed(self, linear):
            self._safety_stop()
            return {**self.motion.status(), "ok": False, "veto": safety_status()["last_veto"]}
        trace = (source, round(float(linear), 1), round(float(angular), 1))
        if source not in {"web", "http"} and trace != self._last_trace_command:
            print(
                f"[level1] command source={source} linear={float(linear):.1f} "
                f"angular={float(angular):.1f}",
                flush=True,
            )
        self._last_trace_command = trace
        out = self.motion.set_velocity(linear, angular)
        return {**out, "ok": True}

    # see video/script/curve_turn_tweak.png for new logic
    @owned_write
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

        self._velocity(y * p, turn, "web")
        return self.drive_status()

    @owned_write
    def drive_tank(self, left, right, seq=None, source="tank"):
        if not self._fresh_motion_seq(seq):
            return self.drive_status(stale=True)
        self.control = {"mode": "manual", "keys": "", "source": source}
        linear = (float(left) + float(right)) / 2
        if command_allowed(self, linear):
            self.motion.tank(left, right)
        else:
            self._safety_stop()
        return self.drive_status()

    @owned_write
    def set_velocity(self, linear, angular, seq=None, source="layer2"):
        if not self._fresh_motion_seq(seq):
            return self.drive_status(stale=True)
        self.control = {"mode": "auto", "keys": "", "source": source}
        self._status_at = 0.0
        return self._velocity(linear, angular, source)

    def snapshot(self):
        return self.camera.snapshot()

    def apply_camera_settings(self, **settings):
        out = self.camera.apply_settings(**settings)
        reset_safety()
        self._status_at = 0.0
        print("[level0] camera settings changed; edge baseline reset", flush=True)
        return out

    def ingest_detections(self, payload):
        self._status_at = 0.0
        out = self.perception.ingest(payload)
        self.spatial_map.observe(
            self.perception.receiver.current(),
            observed_at=(payload or {}).get("captured_at"),
        )
        return out

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

    def find(self, target, search_speed=35, max_cycles=15):
        return find_skill.find(self, target, search_speed, max_cycles)

    def follow(self, target, cycles=0):
        return follow_skill.follow(self, target, cycles=cycles)

    def push(self, target):
        return self.skills.push(target)

    def push_to(self, source, destination):
        return self.skills.push_to(source, destination)

    def emote(self, name, scale=1.0):
        return emotes.run(self, name, scale)

    def calibrate_power(self, **kwargs):
        return self.power_gauge.calibrate(self, **kwargs)

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
            "power_gauge": self.power_gauge.status(),
            "map": self.spatial_map.status(),
            "safety": safety,
            "layers": {
                "level3": {
                    "mode": "remote-vlm",
                    "source": self.perception.receiver.last_packet.get(
                        "source", "none"
                    ),
                    "autonomy": self.autonomy.status(),
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
