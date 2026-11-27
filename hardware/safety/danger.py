"""Procedural table-edge detection from the Pi camera's grayscale stream."""

import statistics
import threading
import time
from collections import deque

try:
    import cv2
    import numpy as np
except Exception:  # pragma: no cover - reported as unavailable at runtime
    cv2 = np = None


class EdgeDetector:
    """Conservative support-surface detector with a stationary-only baseline.

    The detector combines a near/far texture drop with a horizontal boundary
    cue. Its baseline is learned only while stopped, so an edge cannot slowly
    become the new definition of safe ground while the robot advances.
    """

    def __init__(
        self,
        enabled=True,
        warmup_frames=8,
        confirm_frames=2,
        clear_frames=4,
        stale_seconds=0.5,
        drop_threshold=0.42,
    ):
        self.enabled = bool(enabled)
        self.warmup_frames = int(warmup_frames)
        self.confirm_frames = int(confirm_frames)
        self.clear_frames = int(clear_frames)
        self.stale_seconds = float(stale_seconds)
        self.drop_threshold = float(drop_threshold)
        self._safe_ratios = deque(maxlen=90)
        self._safe_near = deque(maxlen=90)
        self._danger_count = 0
        self._clear_count = 0
        self._latched = False
        self._last_frame_at = None
        self._lock = threading.Lock()
        self.last = self._result(False, "initializing", ready=False)

    @staticmethod
    def _texture(region):
        region = region.astype(np.float32)
        gx = cv2.Sobel(region, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(region, cv2.CV_32F, 0, 1, ksize=3)
        return float(np.mean(np.abs(gx)) + np.mean(np.abs(gy)))

    def _features(self, gray):
        h, w = gray.shape[:2]
        # Use the center strip that lies in the robot's forward path.
        x1, x2 = int(w * 0.18), int(w * 0.82)
        y1, y2 = int(h * 0.48), int(h * 0.98)
        support = cv2.GaussianBlur(gray[y1:y2, x1:x2], (5, 5), 0)
        sh = support.shape[0]
        far = support[int(sh * 0.08) : int(sh * 0.42)]
        near = support[int(sh * 0.62) : int(sh * 0.98)]
        far_texture = self._texture(far)
        near_texture = self._texture(near)
        ratio = near_texture / max(far_texture, 1.0)

        vertical = np.mean(
            np.abs(cv2.Sobel(support.astype(np.float32), cv2.CV_32F, 0, 1, ksize=3)),
            axis=1,
        )
        lo, hi = int(sh * 0.18), int(sh * 0.84)
        peak = lo + int(np.argmax(vertical[lo:hi]))
        background = float(np.median(vertical[lo:hi])) + 1.0
        line_strength = float(vertical[peak] / background)
        band = max(3, sh // 18)
        above = support[max(0, peak - 2 * band) : max(1, peak - band)]
        below = support[min(sh - 1, peak + band) : min(sh, peak + 2 * band)]
        boundary_drop = self._texture(below) / max(self._texture(above), 1.0)
        return {
            "ratio": ratio,
            "far_texture": far_texture,
            "near_texture": near_texture,
            "line_strength": line_strength,
            "line_y": (y1 + peak) / h,
            "boundary_drop": boundary_drop,
        }

    @staticmethod
    def _result(danger, reason, ready=False, **metrics):
        return {
            "enabled": True,
            "ready": bool(ready),
            "danger": bool(danger),
            "reason": reason,
            "checked_at": time.time(),
            **metrics,
        }

    def check(self, gray, frame_at=None, learn=False):
        if not self.enabled:
            self.last = {"enabled": False, "ready": False, "danger": False, "reason": "disabled"}
            return self.last
        if cv2 is None or np is None:
            self.last = self._result(True, "opencv unavailable")
            return self.last
        age = None if not frame_at else max(0.0, time.time() - float(frame_at))
        if gray is None or (age is not None and age > self.stale_seconds):
            self.last = self._result(True, "stale camera", frame_age=None if age is None else round(age, 3))
            return self.last

        # The monitor runs faster than grayscale production. One camera frame
        # must never count as several warmup or danger confirmations.
        if frame_at is not None:
            with self._lock:
                if frame_at == self._last_frame_at:
                    return {**self.last, "frame_age": None if age is None else round(age, 3)}
                self._last_frame_at = frame_at

        try:
            features = self._features(gray)
        except Exception as exc:
            self.last = self._result(True, f"compute error: {exc}")
            return self.last

        with self._lock:
            ready = len(self._safe_ratios) >= self.warmup_frames
            baseline = statistics.median(self._safe_ratios) if ready else None
            near_baseline = statistics.median(self._safe_near) if ready and self._safe_near else None
            near_drop = bool(
                near_baseline is not None and features["near_texture"] < near_baseline * 0.65
            )
            ratio_drop = bool(
                ready and near_drop and features["ratio"] < baseline * self.drop_threshold
            )
            boundary = bool(
                features["line_strength"] >= 3.2
                and features["line_y"] >= 0.58
                and features["boundary_drop"] < 0.58
            )
            low_support = features["near_texture"] < 5.0
            candidate = ratio_drop or (boundary and low_support)
            was_latched = self._latched

            if candidate:
                self._danger_count = min(self.confirm_frames, self._danger_count + 1)
                self._clear_count = 0
            else:
                self._danger_count = max(0, self._danger_count - 1)

            if self._danger_count >= self.confirm_frames:
                self._latched = True
            if self._latched and not candidate:
                self._clear_count += 1
                if self._clear_count >= self.clear_frames:
                    self._latched = False
                    self._clear_count = 0
            if (
                not candidate
                and learn
                and not self._latched
                and not was_latched
                and self._danger_count == 0
                and features["far_texture"] >= 4.0
                and features["near_texture"] >= 4.0
            ):
                self._safe_ratios.append(features["ratio"])
                self._safe_near.append(features["near_texture"])
                ready = len(self._safe_ratios) >= self.warmup_frames
                baseline = statistics.median(self._safe_ratios) if ready else None

            danger = self._latched
            reason = "edge ahead" if danger else "candidate" if candidate else "ok" if ready else "calibrating"
            self.last = self._result(
                danger,
                reason,
                ready=ready,
                frame_age=None if age is None else round(age, 3),
                ratio=round(features["ratio"], 3),
                baseline=None if baseline is None else round(baseline, 3),
                line_strength=round(features["line_strength"], 2),
                line_y=round(features["line_y"], 3),
                boundary_drop=round(features["boundary_drop"], 3),
                danger_count=self._danger_count,
                clear_count=self._clear_count,
                latched=self._latched,
                samples=len(self._safe_ratios),
            )
            return self.last

    def reset(self):
        with self._lock:
            self._safe_ratios.clear()
            self._safe_near.clear()
            self._danger_count = 0
            self._clear_count = 0
            self._latched = False
            self._last_frame_at = None
            self.last = self._result(False, "reset", ready=False)
