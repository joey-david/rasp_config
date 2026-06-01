"""SORT-style person tracker: Kalman boxes plus lightweight MOSSE updates."""
from __future__ import annotations

from collections import deque
from itertools import permutations
import os
import threading
import time

import numpy as np

from mischief_common.object_geometry import center, clamp_box, iou, label_score

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None


MAX_YOLO_AGE = float(os.getenv("TRACKER_MAX_YOLO_AGE", "1.5"))
MATCH_IOU = float(os.getenv("TRACKER_MATCH_IOU", "0.3"))
MOSSE_SIZE = int(os.getenv("TRACKER_MOSSE_SIZE", "64"))
MOSSE_PAD = float(os.getenv("TRACKER_MOSSE_PAD", "1.5"))
MOSSE_MIN_PSR = float(os.getenv("TRACKER_MOSSE_MIN_PSR", "5.0"))


def _box_to_z(box):
    x1, y1, x2, y2 = box
    w, h = max(1e-4, x2 - x1), max(1e-4, y2 - y1)
    return np.array([[(x1 + x2) / 2], [(y1 + y2) / 2], [w * h], [w / h]], dtype=float)


def _z_to_box(z):
    u, v, s, r = [float(x) for x in z[:4, 0]]
    s, r = max(1e-6, s), max(1e-6, r)
    w, h = (s * r) ** 0.5, (s / r) ** 0.5
    return clamp_box([u - w / 2, v - h / 2, u + w / 2, v + h / 2])


def _shift_box(box, du=0.0, dv=0.0, ds=0.0):
    z = _box_to_z(box)
    z[0, 0] += du
    z[1, 0] += dv
    z[2, 0] = max(1e-6, z[2, 0] + ds)
    return _z_to_box(z) or box


class KalmanBox:
    """Constant-velocity SORT box state: [u,v,s,r,du,dv,ds]."""

    def __init__(self, box, t=None):
        self.x = np.zeros((7, 1), dtype=float)
        self.x[:4] = _box_to_z(box)
        self.P = np.eye(7) * 0.05
        self.P[4:, 4:] *= 20.0
        self.Q = np.eye(7) * 1e-3
        self.R = np.diag([0.015, 0.015, 0.01, 0.08])
        self.last_t = float(t or time.time())

    def predict(self, t=None):
        t = float(t or time.time())
        dt = max(0.0, min(0.5, t - self.last_t))
        F = np.eye(7)
        F[0, 4] = F[1, 5] = F[2, 6] = dt
        self.x = F @ self.x
        self.x[2, 0] = max(1e-6, self.x[2, 0])
        self.P = F @ self.P @ F.T + self.Q
        self.last_t = t
        return self.box()

    def update(self, box):
        z = _box_to_z(box)
        H = np.zeros((4, 7))
        H[:4, :4] = np.eye(4)
        y = z - H @ self.x
        S = H @ self.P @ H.T + self.R
        K = self.P @ H.T @ np.linalg.inv(S)
        self.x = self.x + K @ y
        self.P = (np.eye(7) - K @ H) @ self.P
        self.x[2, 0] = max(1e-6, self.x[2, 0])
        return self.box()

    def box(self):
        return _z_to_box(self.x)

    def velocity(self):
        return {"du": float(self.x[4, 0]), "dv": float(self.x[5, 0]), "ds": float(self.x[6, 0])}


class Mosse:
    """Tiny MOSSE-like correlation filter on a padded target crop."""

    def __init__(self):
        self.H = None
        self.size = (MOSSE_SIZE, MOSSE_SIZE)
        self.box = None

    def init(self, gray, box):
        patch = self._patch(gray, box)
        if patch is None:
            return False
        x = self._prep(patch)
        g = self._gaussian(*self.size)
        self.H = np.fft.fft2(g) * np.conj(np.fft.fft2(x)) / (np.fft.fft2(x) * np.conj(np.fft.fft2(x)) + 1e-5)
        self.box = box
        return True

    def update(self, gray, predicted_box):
        if self.H is None:
            return predicted_box, 0.0
        patch = self._patch(gray, predicted_box)
        if patch is None:
            return predicted_box, 0.0
        x = self._prep(patch)
        resp = np.fft.ifft2(self.H * np.fft.fft2(x)).real
        y, x0 = np.unravel_index(np.argmax(resp), resp.shape)
        psr = self._psr(resp, x0, y)
        cx = x0 - resp.shape[1] / 2
        cy = y - resp.shape[0] / 2
        box = self._offset(predicted_box, cx / resp.shape[1], cy / resp.shape[0]) if psr >= MOSSE_MIN_PSR else predicted_box
        if psr >= MOSSE_MIN_PSR:
            self.init(gray, box)
        return box, float(psr)

    def _patch(self, gray, box):
        if cv2 is None or gray is None or not box:
            return None
        h, w = gray.shape[:2]
        x1, y1, x2, y2 = box
        cx, cy = (x1 + x2) / 2 * w, (y1 + y2) / 2 * h
        bw, bh = max(8, (x2 - x1) * w * MOSSE_PAD), max(8, (y2 - y1) * h * MOSSE_PAD)
        a, b, c, d = int(cx - bw / 2), int(cy - bh / 2), int(cx + bw / 2), int(cy + bh / 2)
        if c <= 0 or d <= 0 or a >= w or b >= h:
            return None
        patch = gray[max(0, b):min(h, d), max(0, a):min(w, c)]
        if patch.shape[0] < 4 or patch.shape[1] < 4:
            return None
        return cv2.resize(patch, self.size, interpolation=cv2.INTER_AREA)

    def _offset(self, box, ox, oy):
        x1, y1, x2, y2 = box
        dx, dy = ox * (x2 - x1) * MOSSE_PAD, oy * (y2 - y1) * MOSSE_PAD
        return clamp_box([x1 + dx, y1 + dy, x2 + dx, y2 + dy]) or box

    @staticmethod
    def _prep(patch):
        x = np.log(np.float32(patch) + 1.0)
        x = (x - x.mean()) / (x.std() + 1e-5)
        return x * np.outer(np.hanning(x.shape[0]), np.hanning(x.shape[1]))

    @staticmethod
    def _gaussian(w, h, sigma=2.0):
        xs, ys = np.meshgrid(np.arange(w) - w / 2, np.arange(h) - h / 2)
        return np.exp(-0.5 * (xs * xs + ys * ys) / (sigma * sigma))

    @staticmethod
    def _psr(resp, x, y):
        side = resp.copy()
        side[max(0, y - 5):y + 6, max(0, x - 5):x + 6] = np.nan
        vals = side[~np.isnan(side)]
        return (resp[y, x] - vals.mean()) / (vals.std() + 1e-5)


class Track:
    def __init__(self, tid, label, box, score, frame_t, raw_id=None, model=None):
        self.id = tid
        self.label = label
        self.score = float(score)
        self.kf = KalmanBox(box, frame_t)
        self.mosse = Mosse()
        self.raw_id = raw_id
        self.model = model
        self.created_at = time.time()
        self.last_yolo_at = time.time()
        self.tracked_at = frame_t
        self.quality = max(0.1, float(score))
        self.psr = 0.0

    def predict(self, frame_t):
        return self.kf.predict(frame_t)

    def update_yolo(self, box, score, frame_t, gray=None, raw_id=None, model=None):
        self.score = float(score)
        self.kf.update(box)
        self.last_yolo_at = time.time()
        self.tracked_at = frame_t
        self.raw_id = raw_id or self.raw_id
        self.model = model or self.model
        self.quality = min(1.0, 0.7 * self.score + 0.3 * self.quality)
        if gray is not None:
            self.mosse.init(gray, self.kf.box())

    def update_pixels(self, gray, frame_t):
        pred = self.predict(frame_t)
        if gray is None or pred is None:
            return
        box, psr = self.mosse.update(gray, pred)
        self.psr = psr
        if psr >= MOSSE_MIN_PSR:
            self.kf.update(box)
            self.quality = min(1.0, self.quality * 0.995 + 0.01)
        else:
            self.quality *= 0.9
        self.tracked_at = frame_t

    def as_dict(self):
        box = self.kf.box()
        age = max(0.0, time.time() - self.tracked_at)
        yolo_age = max(0.0, time.time() - self.last_yolo_at)
        return {
            "id": self.id, "track_id": self.id, "label": self.label,
            "score": round(self.score, 4), "box": box, "center": center(box),
            "source": "pi-sort-mosse", "raw_id": self.raw_id, "model": self.model,
            "quality": round(max(0.0, self.quality * max(0.0, 1 - age / 1.5)), 3),
            "age": round(age, 3), "yolo_age": round(yolo_age, 3),
            "tracked_at": self.tracked_at, "velocity": self.kf.velocity(),
            "psr": round(float(self.psr), 3),
        }


class BoxTracker:
    def __init__(self, max_frames=90, max_age=1.5):
        self.frames = deque(maxlen=max_frames)
        self.active = {}
        self.max_age = max_age
        self.next_id = 1
        self.error = ""
        self.update_times = deque(maxlen=120)
        self.last_update_at = 0.0
        self.last_step_ms = 0.0
        self.last_ingest_ms = 0.0
        self._lock = threading.RLock()

    def add_frame(self, frame_jpeg, frame_at, motion_status=None):
        if not frame_jpeg or not frame_at or cv2 is None:
            return
        try:
            arr = np.frombuffer(frame_jpeg, dtype=np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
            self.add_gray(img, frame_at, motion_status)
        except Exception as e:
            with self._lock:
                self.error = str(e)

    def add_gray(self, gray, frame_at, motion_status=None):
        if gray is None or not frame_at or cv2 is None:
            return
        started = time.time()
        try:
            with self._lock:
                self.frames.append({"t": float(frame_at), "gray": gray})
                for track in list(self.active.values()):
                    track.update_pixels(gray, float(frame_at))
                self._prune()
                self.last_update_at = float(frame_at)
                self.last_step_ms = round((time.time() - started) * 1000, 3)
                self.update_times.append(time.time())
                self.error = ""
        except Exception as e:
            with self._lock:
                self.error = str(e)

    def ingest(self, payload):
        started = time.time()
        with self._lock:
            gray = self.frames[-1]["gray"] if self.frames else None
            frame_t = self.frames[-1]["t"] if self.frames else time.time()
            detections = [(d, clamp_box(d.get("box"))) for d in payload.get("detections") or []]
            detections = [(d, b) for d, b in detections if b and str(d.get("label") or "").strip()]
            self._match_detections(detections, gray, frame_t, payload)
            self._prune()
            self.last_ingest_ms = round((time.time() - started) * 1000, 3)
        return self.tracks()

    def track(self, track_id):
        with self._lock:
            t = self.active.get(int(track_id)) if track_id is not None else None
            return t.as_dict() if t else None

    def tracks(self):
        with self._lock:
            return self._tracks_unlocked()

    def best(self, query):
        matches = [(label_score(query, t), t) for t in self.tracks()]
        matches = [(s, t) for s, t in matches if s > 0.45]
        return max(matches, key=lambda x: (x[0], x[1]["quality"], x[1].get("score", 0)))[1] if matches else None

    def status(self):
        with self._lock:
            now = time.time()
            recent = [t for t in self.update_times if now - t <= 2.0]
            return {
                "tracks": self._tracks_unlocked(),
                "frame_buffer": len(self.frames),
                "error": self.error,
                "backend": "sort-mosse",
                "update_hz": round(len(recent) / 2.0, 1) if recent else 0.0,
                "last_update_age": None if not self.last_update_at else round(max(0.0, now - self.last_update_at), 3),
                "last_step_ms": self.last_step_ms,
                "last_ingest_ms": self.last_ingest_ms,
                "active": len(self.active),
                "max_yolo_age": MAX_YOLO_AGE,
                "mosse_min_psr": MOSSE_MIN_PSR,
            }

    def has_active(self):
        with self._lock:
            self._prune()
            return bool(self.active)

    def _tracks_unlocked(self):
        return sorted([t.as_dict() for t in self.active.values()
                       if t.kf.box() and t.as_dict()["quality"] > 0],
                      key=lambda x: (x["label"], -x["quality"]))

    def _match_detections(self, detections, gray, frame_t, payload):
        tracks = list(self.active.values())
        pairs = self._assign(tracks, detections)
        matched_dets = set()
        for ti, di in pairs:
            track, (det, box) = tracks[ti], detections[di]
            if iou(track.kf.box(), box) < MATCH_IOU:
                continue
            dt = max(0.0, frame_t - float(payload.get("captured_at") or frame_t))
            v = track.kf.velocity()
            corrected = _shift_box(box, v["du"] * dt, v["dv"] * dt, v["ds"] * dt)
            track.update_yolo(corrected, det.get("score", 1.0), frame_t, gray,
                              det.get("id"), payload.get("model", det.get("model")))
            matched_dets.add(di)
        for di, (det, box) in enumerate(detections):
            if di in matched_dets:
                continue
            tid = self._new_id()
            track = Track(tid, str(det.get("label")).strip(), box, det.get("score", 1.0),
                          frame_t, det.get("id"), payload.get("model", det.get("model")))
            if gray is not None:
                track.mosse.init(gray, box)
            self.active[tid] = track

    def _assign(self, tracks, detections):
        if not tracks or not detections:
            return []
        scores = [[iou(t.kf.box(), box) for _, box in detections] for t in tracks]
        try:
            from scipy.optimize import linear_sum_assignment
            rows, cols = linear_sum_assignment([[-s for s in row] for row in scores])
            return list(zip(rows, cols))
        except Exception:
            n, m = len(tracks), len(detections)
            if max(n, m) <= 7:
                best = []
                best_score = -1
                for cols in permutations(range(m), min(n, m)):
                    total = sum(scores[i][c] for i, c in enumerate(cols))
                    if total > best_score:
                        best_score = total
                        best = list(enumerate(cols))
                return best
            used = set()
            out = []
            for i, row in enumerate(scores):
                c = max((j for j in range(len(row)) if j not in used), key=lambda j: row[j], default=None)
                if c is not None:
                    used.add(c)
                    out.append((i, c))
            return out

    def _new_id(self):
        tid = self.next_id
        self.next_id += 1
        return tid

    def _prune(self):
        now = time.time()
        for tid, track in list(self.active.items()):
            if now - track.last_yolo_at > MAX_YOLO_AGE or now - track.tracked_at > self.max_age:
                del self.active[tid]
