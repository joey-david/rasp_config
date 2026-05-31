"""Cheap Pi-side tracking-by-detection for delayed PC boxes."""
from __future__ import annotations

from collections import deque
import threading
import time

from mischief_common.object_geometry import center, clamp_box, iou, label_score

try:
    import cv2
    import numpy as np
except Exception:  # pragma: no cover - allows service boot without OpenCV
    cv2 = None
    np = None


SIZE = (320, 240)


class BoxTracker:
    def __init__(self, max_frames=30, max_age=1.5):
        self.frames = deque(maxlen=max_frames)
        self.active = {}
        self.max_age = max_age
        self.next_id = 1
        self.error = ""
        self._lock = threading.RLock()

    def add_frame(self, frame_jpeg, frame_at, motion_status=None):
        if not frame_jpeg or not frame_at or cv2 is None:
            return
        try:
            arr = np.frombuffer(frame_jpeg, dtype=np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
            if img is None:
                return
            gray = cv2.resize(img, SIZE, interpolation=cv2.INTER_AREA)
            self.add_gray(gray, frame_at, motion_status)
        except Exception as e:
            with self._lock:
                self.error = str(e)

    def add_gray(self, gray, frame_at, motion_status=None):
        if gray is None or not frame_at or cv2 is None:
            return
        try:
            if gray.shape[1::-1] != SIZE:
                gray = cv2.resize(gray, SIZE, interpolation=cv2.INTER_AREA)
            item = {"t": float(frame_at), "gray": gray, "motion": motion_status or {}}
            with self._lock:
                if self.frames:
                    self._advance(self.frames[-1], item)
                self.frames.append(item)
                self._prune()
                self.error = ""
        except Exception as e:
            with self._lock:
                self.error = str(e)

    def ingest(self, payload):
        with self._lock:
            if not self.frames:
                return self._tracks_unlocked()
            anchor = self._nearest(float(payload.get("captured_at") or self.frames[-1]["t"]))
            for i, d in enumerate(payload.get("detections") or []):
                label = str(d.get("label") or "").strip()
                box = clamp_box(d.get("box"))
                if not label or not box:
                    continue
                tid = self._match(label, box) or self._new_id()
                points = self._points(anchor["gray"], box)
                track = {
                    "id": tid,
                    "track_id": tid,
                    "label": label,
                    "score": float(d.get("score", 1.0)),
                    "box": box,
                    "points": points,
                    "initial_points": max(1, len(points) if points is not None else 0),
                    "source": "pi-tracker",
                    "detected_at": payload.get("captured_at"),
                    "inferred_at": payload.get("inferred_at"),
                    "received_at": payload.get("received_at", time.time()),
                    "tracked_at": anchor["t"],
                    "raw_id": d.get("id") or f"{payload.get('frame_id', 'frame')}:{i}",
                    "model": payload.get("model", d.get("model")),
                    "quality": 0.2 if points is None else 1.0,
                }
                self.active[tid] = track
                self._replay(track, anchor)
            self._prune()
        return self.tracks()

    def tracks(self):
        with self._lock:
            return self._tracks_unlocked()

    def _tracks_unlocked(self):
        now = time.time()
        out = []
        for t in self.active.values():
            age = now - float(t.get("detected_at") or t.get("tracked_at") or now)
            quality = max(0.0, float(t.get("quality", 0)) * max(0.0, 1 - age / self.max_age))
            if quality <= 0:
                continue
            box = clamp_box(t["box"])
            if not box:
                continue
            out.append({
                k: v for k, v in t.items()
                if k not in {"points", "initial_points"}
            } | {
                "box": box,
                "center": center(box),
                "age": round(age, 3),
                "quality": round(quality, 3),
            })
        return sorted(out, key=lambda x: (x["label"], -x["quality"]))

    def best(self, query):
        matches = [(label_score(query, t), t) for t in self.tracks()]
        matches = [(s, t) for s, t in matches if s > 0.45]
        return max(matches, key=lambda x: (x[0], x[1]["quality"], x[1].get("score", 0)))[1] if matches else None

    def status(self):
        with self._lock:
            return {"tracks": self._tracks_unlocked(), "frame_buffer": len(self.frames), "error": self.error, "backend": "lk-flow"}

    def has_active(self):
        with self._lock:
            self._prune()
            return bool(self.active)

    def _nearest(self, t):
        return min(self.frames, key=lambda f: abs(f["t"] - t))

    def _match(self, label, box):
        same = [t for t in self.active.values() if t["label"].lower() == label.lower()]
        hit = max(same, key=lambda t: iou(t["box"], box), default=None)
        return hit["id"] if hit and iou(hit["box"], box) > 0.15 else None

    def _new_id(self):
        tid = self.next_id
        self.next_id += 1
        return tid

    def _points(self, gray, box):
        x1, y1, x2, y2 = box
        w, h = SIZE
        mask = np.zeros((h, w), dtype=np.uint8)
        mask[int(y1 * h):int(y2 * h), int(x1 * w):int(x2 * w)] = 255
        return cv2.goodFeaturesToTrack(gray, maxCorners=60, qualityLevel=0.01, minDistance=4, mask=mask)

    def _replay(self, track, anchor):
        try:
            start = list(self.frames).index(anchor)
        except ValueError:
            return
        for old, new in zip(list(self.frames)[start:], list(self.frames)[start + 1:]):
            self._flow(track, old, new)

    def _advance(self, old, new):
        for track in list(self.active.values()):
            self._flow(track, old, new)

    def _flow(self, track, old, new):
        pts = track.get("points")
        if pts is None or len(pts) < 3:
            track["quality"] = min(track.get("quality", 0.2), 0.25)
            track["tracked_at"] = new["t"]
            return
        nxt, st, _ = cv2.calcOpticalFlowPyrLK(old["gray"], new["gray"], pts, None)
        good_old, good_new = pts[st == 1], nxt[st == 1]
        if len(good_new) < 3:
            track["points"], track["quality"], track["tracked_at"] = None, 0.1, new["t"]
            return
        dx, dy = np.median(good_new - good_old, axis=0)
        x1, y1, x2, y2 = track["box"]
        track["box"] = clamp_box([x1 + dx / SIZE[0], y1 + dy / SIZE[1], x2 + dx / SIZE[0], y2 + dy / SIZE[1]])
        track["points"] = good_new.reshape(-1, 1, 2)
        track["tracked_at"] = new["t"]
        track["quality"] = min(1.0, len(good_new) / max(1, track.get("initial_points", len(good_new))))

    def _prune(self):
        now = time.time()
        for tid, track in list(self.active.items()):
            if now - float(track.get("tracked_at") or 0) > self.max_age:
                del self.active[tid]
