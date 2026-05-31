"""Layer 0 visual safety scaffold.

This is intentionally conservative and non-semantic. It estimates whether the
bottom of the frame contains enough floor-like texture/brightness continuity to
allow forward motion. It is a placeholder for a calibrated edge model, but it
has the right local-only API and never depends on PC detections.
"""
import time

try:
    import cv2
    import numpy as np
    from PIL import Image
    import io
except Exception:  # keep robot bootable if optional vision deps are missing
    cv2 = np = Image = io = None


class EdgeSafety:
    def __init__(self, enabled=False, min_floor_score=0.08):
        self.enabled = enabled
        self.min_floor_score = min_floor_score
        self.last = {"enabled": enabled, "danger": False, "reason": "not checked"}

    def check(self, jpeg=None, gray=None):
        if not self.enabled:
            self.last = {"enabled": False, "danger": False, "reason": "disabled"}
            return self.last
        if gray is None and not (jpeg and cv2 and np and Image):
            self.last = {"enabled": True, "danger": False, "reason": "no frame/deps"}
            return self.last

        img = gray if gray is not None else np.asarray(Image.open(io.BytesIO(jpeg)).convert("L"))
        h = img.shape[0]
        lower = img[int(h * 0.72):]
        edges = cv2.Canny(lower, 60, 160)
        floor_score = float(edges.mean() / 255.0)
        danger = floor_score < self.min_floor_score
        self.last = {
            "enabled": True,
            "danger": danger,
            "floor_score": round(floor_score, 4),
            "reason": "low floor texture" if danger else "ok",
            "checked_at": time.time(),
        }
        return self.last
