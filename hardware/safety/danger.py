"""Layer 0 visual edge detection — table/counter edge safety.

Uses Laplacian variance ratio (bottom 20% / middle 20% of frame).
Close surfaces have high spatial detail; a table edge reveals the
floor far below (low detail). The ratio drops sharply at an edge.

Carpets at floor level don't trigger because the distance (and thus
detail level) is consistent with surrounding floor — the bottom/middle
ratio stays stable.

Pi-only. No PC dependency. Runs on the grayscale frame buffer.
"""

import time
import threading
from collections import deque

try:
    import cv2
    import numpy as np
except Exception:
    cv2 = np = None


class EdgeDetector:
    """Detect surface edges ahead of the robot using monocular texture sharpness.

    Maintains a rolling window of bottom/middle Laplacian variance ratios.
    Flags danger when the ratio drops significantly below its recent mean,
    indicating the bottom of the frame shows a surface much farther away
    than the middle (i.e., the table ends and the floor is below).
    """

    def __init__(self, enabled: bool = True, window_frames: int = 30,
                 drop_threshold: float = 0.45, confirm_frames: int = 3):
        """
        Args:
            enabled: whether edge detection is active
            window_frames: rolling window size for baseline ratio
            drop_threshold: ratio below baseline_mean * threshold → edge
            confirm_frames: consecutive frames below threshold to confirm
        """
        self.enabled = enabled
        self.drop_threshold = drop_threshold
        self.confirm_frames = confirm_frames
        self._window: deque[float] = deque(maxlen=window_frames)
        self._danger_count = 0
        self._lock = threading.Lock()
        self.last: dict = {"enabled": enabled, "danger": False, "reason": "idle",
                           "ratio": None, "baseline": None}

    def check(self, gray) -> dict:
        """Check a 320x240 grayscale frame for edge danger."""
        if not self.enabled or gray is None or cv2 is None:
            self.last = {"enabled": self.enabled, "danger": False,
                         "reason": "disabled" if not self.enabled else "no frame"}
            return self.last

        try:
            h = gray.shape[0]
            bottom = gray[int(h * 0.80):, :]
            middle = gray[int(h * 0.35):int(h * 0.55), :]

            bv = cv2.Laplacian(bottom, cv2.CV_64F).var()
            mv = cv2.Laplacian(middle, cv2.CV_64F).var()
            ratio = bv / max(mv, 1e-6)
        except Exception as e:
            self.last = {"enabled": True, "danger": False,
                         "reason": f"compute error: {e}"}
            return self.last

        with self._lock:
            self._window.append(ratio)

            # Need warmup before we can detect drops
            if len(self._window) < 10:
                self.last = {"enabled": True, "danger": False,
                             "reason": "warmup", "ratio": round(ratio, 3)}
                return self.last

            baseline = sum(self._window) / len(self._window)
            edge_threshold = baseline * self.drop_threshold

            if ratio < edge_threshold:
                self._danger_count += 1
            else:
                self._danger_count = max(0, self._danger_count - 1)

            danger = self._danger_count >= self.confirm_frames

            self.last = {
                "enabled": True,
                "danger": danger,
                "reason": "edge ahead" if danger else "ok",
                "ratio": round(ratio, 3),
                "baseline": round(baseline, 3),
                "threshold": round(edge_threshold, 3),
                "danger_count": self._danger_count,
                "checked_at": time.time(),
            }
            return self.last

    def reset(self):
        """Clear rolling window (e.g. after robot repositioned)."""
        with self._lock:
            self._window.clear()
            self._danger_count = 0
            self.last = {"enabled": self.enabled, "danger": False,
                         "reason": "reset"}
