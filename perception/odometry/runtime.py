"""Robot-facing odometry API using the latest camera frame."""

import os
import time

try:
    import cv2
    import numpy as np
except Exception:  # pragma: no cover - Pi runtime dependency
    cv2 = np = None

from .angular import AngularSpeedEstimator

DEFAULT_FX_PX = float(os.environ.get("ODOMETRY_FX_PX", "48.5"))
DEFAULT_MIN_SCORE = float(os.environ.get("ODOMETRY_MIN_SCORE", "0.08"))
DEFAULT_WIDTH = int(os.environ.get("ODOMETRY_WIDTH", "160"))
DEFAULT_HEIGHT = int(os.environ.get("ODOMETRY_HEIGHT", "120"))
ANGULAR_SIGN = float(os.environ.get("ODOMETRY_ANGULAR_SIGN", "-1"))


class RobotOdometry:
    def __init__(self, robot, fx_px=DEFAULT_FX_PX, min_score=DEFAULT_MIN_SCORE):
        self.robot = robot
        self.angular = AngularSpeedEstimator(fx_px=fx_px)
        self.min_score = min_score
        self.target_rad_s = 0.0
        self.last = {"rad_s": 0.0, "fresh": False, "score": 0.0}
        self._frame_id = None

    def _gray(self):
        if cv2 is None or np is None:
            return None, 0.0, None, "opencv unavailable"
        frame, frame_at, frame_id = self.robot.camera.latest()
        if not frame or frame_id == self._frame_id:
            return None, frame_at, frame_id, "no new frame"
        arr = np.frombuffer(frame, dtype=np.uint8)
        gray = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
        if gray is None:
            return None, frame_at, frame_id, "decode failed"
        gray = cv2.resize(
            gray, (DEFAULT_WIDTH, DEFAULT_HEIGHT), interpolation=cv2.INTER_AREA
        )
        return gray, frame_at or time.time(), frame_id, ""

    def reset(self):
        self.angular.prev = None
        self.angular.prev_t = None
        self._frame_id = None
        self.last = {"rad_s": 0.0, "fresh": False, "score": 0.0}

    def update(self):
        gray, frame_at, frame_id, error = self._gray()
        if gray is None:
            self.last = {**self.last, "fresh": False, "error": error}
            return self.last
        self._frame_id = frame_id
        out = self.angular.update(gray, frame_at)
        if not out:
            self.last = {
                "rad_s": 0.0,
                "fresh": False,
                "score": 0.0,
                "frame_id": frame_id,
                "target_rad_s": self.target_rad_s,
            }
            return self.last
        fresh = out["score"] >= self.min_score
        rad_s = ANGULAR_SIGN * out["rad_s"]
        self.last = {
            "rad_s": rad_s,
            "visual_rad_s": out["rad_s"],
            "fresh": fresh,
            "score": out["score"],
            "dx": out["dx"],
            "dt": out["dt"],
            "frame_id": frame_id,
            "target_rad_s": self.target_rad_s,
        }
        return self.last

    def rotation_rad_s(self):
        return self.update().get("rad_s", 0.0)

    def set_rotation_target(self, rad_s):
        self.target_rad_s = float(rad_s)
        self.last = {**self.last, "target_rad_s": self.target_rad_s}
        return self.status()

    def status(self):
        return {**self.last, "target_rad_s": self.target_rad_s}
