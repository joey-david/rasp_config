"""Robot-facing odometry API using the latest camera frame."""

import os
import time

try:
    import cv2
    import numpy as np
except Exception:  # pragma: no cover - Pi runtime dependency
    cv2 = np = None

from .angular import AngularSpeedEstimator
from .linear import LinearSpeedEstimator

DEFAULT_FX_PX = float(os.environ.get("ODOMETRY_FX_PX", "48.5"))
DEFAULT_MIN_SCORE = float(os.environ.get("ODOMETRY_MIN_SCORE", "0.08"))
DEFAULT_WIDTH = int(os.environ.get("ODOMETRY_WIDTH", "160"))
DEFAULT_HEIGHT = int(os.environ.get("ODOMETRY_HEIGHT", "120"))
ANGULAR_SIGN = float(os.environ.get("ODOMETRY_ANGULAR_SIGN", "-1"))


class RobotOdometry:
    def __init__(self, robot, fx_px=DEFAULT_FX_PX, min_score=DEFAULT_MIN_SCORE):
        self.robot = robot
        self.angular = AngularSpeedEstimator(fx_px=fx_px)
        self.linear = LinearSpeedEstimator()
        self.min_score = min_score
        self.last = {"rad_s": 0.0, "fresh": False, "score": 0.0}
        self._frame_id = None

    def _decode_gray(self, frame):
        arr = np.frombuffer(frame, dtype=np.uint8)
        gray = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
        if gray is None:
            return None
        return cv2.resize(
            gray, (DEFAULT_WIDTH, DEFAULT_HEIGHT), interpolation=cv2.INTER_AREA
        )

    def capture_gray(self, after_frame_id=None, timeout=0.08):
        """Capture one grayscale frame without mutating streaming odometry state."""
        if cv2 is None or np is None:
            return None, 0.0, None, "opencv unavailable"
        if after_frame_id is not None and hasattr(self.robot.camera, "snapshot_with_meta"):
            frame, frame_at, frame_id = self.robot.camera.snapshot_with_meta(
                timeout=timeout, after_frame_id=after_frame_id
            )
            if not frame or frame_id <= after_frame_id:
                return None, frame_at, frame_id, "no new frame"
        else:
            frame, frame_at, frame_id = self.robot.camera.latest()
            if not frame:
                return None, frame_at, frame_id, "no frame"
        gray = self._decode_gray(frame)
        if gray is None:
            return None, frame_at, frame_id, "decode failed"
        return gray, frame_at or time.time(), frame_id, ""

    def measure_shift(self, before_gray, after_gray):
        """Measure horizontal/vertical image shift between two independent frames."""
        if cv2 is None or np is None or before_gray is None or after_gray is None:
            return {"fresh": False, "linear_fresh": False, "dx": 0.0, "dy": 0.0, "score": 0.0, "linear_score": 0.0}
        h = before_gray.shape[0]
        a_lo, a_hi = int(h * self.angular.roi[0]), int(h * self.angular.roi[1])
        l_lo, l_hi = int(h * self.linear.roi[0]), int(h * self.linear.roi[1])
        (dx, _), a_score = cv2.phaseCorrelate(
            before_gray[a_lo:a_hi].astype(np.float32),
            after_gray[a_lo:a_hi].astype(np.float32),
        )
        (_, dy), l_score = cv2.phaseCorrelate(
            before_gray[l_lo:l_hi].astype(np.float32),
            after_gray[l_lo:l_hi].astype(np.float32),
        )
        return {
            "fresh": bool(a_score >= self.min_score),
            "linear_fresh": bool(l_score >= self.min_score),
            "dx": float(dx),
            "dy": float(dy),
            "score": float(a_score),
            "linear_score": float(l_score),
        }

    def reset(self):
        self.angular.prev = None
        self.angular.prev_t = None
        self.linear.prev = None
        self.linear.prev_t = None
        self._frame_id = None
        self.last = {"rad_s": 0.0, "fresh": False, "score": 0.0}

    def observe_gray(self, gray, frame_at, frame_id):
        if frame_id == self._frame_id:
            return
        previous = self.last.get("frame_at")
        if previous is None or not 0 < frame_at - previous <= 0.5:
            self.reset()
        gray = cv2.resize(gray, (DEFAULT_WIDTH, DEFAULT_HEIGHT), interpolation=cv2.INTER_AREA)
        self._frame_id = frame_id
        angular = self.angular.update(gray, frame_at)
        linear = self.linear.update(gray, frame_at)
        if not angular or not linear:
            self.last = {
                "rad_s": 0.0,
                "fresh": False,
                "score": 0.0,
                "frame_id": frame_id,
                "frame_at": frame_at,
            }
            return self.last
        angular_fresh = angular["score"] >= self.min_score
        linear_fresh = linear["score"] >= self.min_score
        rad_s = ANGULAR_SIGN * angular["rad_s"]
        self.last = {
            "rad_s": rad_s,
            "visual_rad_s": angular["rad_s"],
            "fresh": angular_fresh,
            "score": angular["score"],
            "dx": angular["dx"],
            "dt": angular["dt"],
            "linear_fresh": linear_fresh,
            "linear_score": linear["score"],
            "dy": linear["dy"],
            "relative_linear_px_s": linear["dy"] / linear["dt"],
            "frame_id": frame_id,
            "frame_at": frame_at,
        }
        return self.last

    def status(self):
        sample = dict(self.last)
        if not 0 <= time.time() - sample.get("frame_at", 0) <= 0.5:
            sample.update(fresh=False, linear_fresh=False)
        return sample
