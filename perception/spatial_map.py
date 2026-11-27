"""Small egocentric map built from command odometry and image-space detections."""

from collections import deque
import math
import os
import threading
import time


HFOV_RAD = math.radians(float(os.getenv("CAMERA_HFOV_DEG", "62")))
LINEAR_UNITS_S = float(os.getenv("MAP_LINEAR_UNITS_S_AT_100", "1.0"))
MAX_COMMAND_SECONDS = float(os.getenv("MOTOR_WATCHDOG_SECONDS", "0.75"))
HISTORY_SECONDS = 30.0

# One-turn timings measured in calibrations/odometry. Values outside the
# reliable 30-45 range are intentionally clamped to its endpoints.
TURN_RATE = ((30.0, 2.246), (35.0, 1.611), (40.0, 2.213), (45.0, 2.602))


def _turn_rate(command):
    value = abs(float(command))
    if value < TURN_RATE[0][0]:
        return 0.0
    for (p0, r0), (p1, r1) in zip(TURN_RATE, TURN_RATE[1:]):
        if value <= p1:
            alpha = (value - p0) / (p1 - p0)
            return math.copysign(r0 + alpha * (r1 - r0), command)
    return math.copysign(TURN_RATE[-1][1], command)


def _advance_pose(x, z, yaw, linear, angular, seconds):
    dt = max(0.0, min(MAX_COMMAND_SECONDS, float(seconds)))
    omega = _turn_rate(angular)
    next_yaw = yaw + omega * dt
    speed = float(linear) / 100.0 * LINEAR_UNITS_S
    if abs(omega) < 1e-6:
        x += math.sin(yaw) * speed * dt
        z += math.cos(yaw) * speed * dt
    else:
        x += speed * (math.cos(yaw) - math.cos(next_yaw)) / omega
        z += speed * (math.sin(next_yaw) - math.sin(yaw)) / omega
    yaw = (next_yaw + math.pi) % (2 * math.pi) - math.pi
    return x, z, yaw


class SpatialMap:
    """Relative navigation memory; deliberately does not claim metric SLAM."""

    def __init__(self):
        self._lock = threading.RLock()
        self._at = time.time()
        self._linear = self._angular = 0.0
        self.x = self.z = self.yaw = 0.0
        self._objects = []
        self._next_id = 1
        self._segments = deque(maxlen=512)
        self._record(self._at)

    def _integrate(self, now):
        if now < self._at:
            self._at = now
            self._segments.clear()
            self._record(now)
            return
        self.x, self.z, self.yaw = _advance_pose(
            self.x,
            self.z,
            self.yaw,
            self._linear,
            self._angular,
            now - self._at,
        )
        self._at = now

    def _record(self, now):
        segment = (
            now,
            self.x,
            self.z,
            self.yaw,
            self._linear,
            self._angular,
        )
        if self._segments and self._segments[-1][0] == now:
            self._segments[-1] = segment
        else:
            self._segments.append(segment)
        while len(self._segments) > 1 and now - self._segments[0][0] > HISTORY_SECONDS:
            self._segments.popleft()

    def _pose_at(self, observed_at):
        try:
            at = min(self._at, float(observed_at))
        except Exception:
            return self.x, self.z, self.yaw
        segment = self._segments[0]
        for item in reversed(self._segments):
            if item[0] <= at:
                segment = item
                break
        started, x, z, yaw, linear, angular = segment
        return _advance_pose(x, z, yaw, linear, angular, at - started)

    def command(self, linear, angular, now=None):
        with self._lock:
            now = time.time() if now is None else now
            self._integrate(now)
            self._linear, self._angular = float(linear), float(angular)
            self._record(now)

    def observe(self, detections, now=None, observed_at=None):
        now = time.time() if now is None else now
        with self._lock:
            self._integrate(now)
            camera_x, camera_z, camera_yaw = self._pose_at(observed_at)
            for det in detections or []:
                center = det.get("center") or (0.5, 0.5)
                depth = min(10.0, max(0.2, float(det.get("relative_depth", 5.0))))
                bearing = (float(center[0]) - 0.5) * HFOV_RAD
                angle = camera_yaw + bearing
                x = camera_x + math.sin(angle) * depth
                z = camera_z + math.cos(angle) * depth
                same = [o for o in self._objects if o["label"] == det.get("label")]
                match = min(same, key=lambda o: math.hypot(o["x"] - x, o["z"] - z), default=None)
                if match and math.hypot(match["x"] - x, match["z"] - z) <= max(0.8, depth * 0.3):
                    alpha = 0.35
                    match.update(
                        x=match["x"] * (1 - alpha) + x * alpha,
                        z=match["z"] * (1 - alpha) + z * alpha,
                        relative_depth=depth,
                        score=det.get("score"),
                        seen_at=now,
                    )
                else:
                    self._objects.append({
                        "id": f"landmark-{self._next_id}",
                        "label": det.get("label"),
                        "x": x,
                        "z": z,
                        "relative_depth": depth,
                        "score": det.get("score"),
                        "seen_at": now,
                    })
                    self._next_id += 1
            self._objects = [o for o in self._objects if now - o["seen_at"] <= 120]

    def reset(self):
        with self._lock:
            self._at = time.time()
            self._linear = self._angular = self.x = self.z = self.yaw = 0.0
            self._objects.clear()
            self._segments.clear()
            self._record(self._at)

    def status(self):
        with self._lock:
            self._integrate(time.time())
            return {
                "metric": False,
                "depth": "relative-bounding-box-scale",
                "pose": {"x": round(self.x, 3), "z": round(self.z, 3), "yaw": round(self.yaw, 3)},
                "objects": [{**o, "x": round(o["x"], 3), "z": round(o["z"], 3)} for o in self._objects],
                "calibration": {"turn_power_range": [30, 45], "linear": "uncalibrated-relative-units"},
            }
