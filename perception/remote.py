"""Remote perception ingest from the PC visual cortex."""
import threading
import time

from .receiver import DetectionReceiver
from .tracker import BoxTracker


class RemotePerception:
    def __init__(self, memory=None, camera=None, motion=None, fresh_seconds=1.0, stale_seconds=10.0):
        self.memory = memory
        self.camera = camera
        self.motion = motion
        self.receiver = DetectionReceiver()
        self.tracker = BoxTracker()
        self.fresh_seconds = fresh_seconds
        self.stale_seconds = stale_seconds
        self.error = ""
        self._stop = threading.Event()
        self._worker = None

    @property
    def detections(self):
        return self.receiver.latest

    @property
    def tracks(self):
        return self.tracker.tracks()

    def start(self):
        if not self.camera or self._worker:
            return
        self._worker = threading.Thread(target=self._frame_worker, daemon=True)
        self._worker.start()

    def stop(self):
        self._stop.set()

    def _frame_worker(self):
        while not self._stop.is_set():
            try:
                motion = self.motion.status() if self.motion else {}
                if hasattr(self.camera, "gray_snapshot"):
                    gray, frame_at = self.camera.gray_snapshot(timeout=1)
                    self.tracker.add_gray(gray, frame_at, motion)
                else:
                    frame = self.camera.snapshot(timeout=1)
                    self.tracker.add_frame(frame, self.camera.frame_at, motion)
            except Exception as e:
                self.error = str(e)
                time.sleep(0.1)

    def ingest(self, payload):
        packet, detections = self.receiver.ingest(payload)
        self.error = ""
        tracks = self.tracker.ingest({**packet, "detections": detections})
        if self.memory:
            self.memory.update([t for t in tracks if t.get("quality", 0) > 0.4])
        return self.status()

    def is_fresh(self):
        return bool(self.receiver.received_at and time.time() - self.receiver.received_at <= self.fresh_seconds)

    def best(self, query):
        return self.tracker.best(query)

    def status(self):
        now = time.time()
        age = None if not self.receiver.received_at else round(now - self.receiver.received_at, 3)
        tracker = self.tracker.status()
        return {
            "detections": self.receiver.latest,
            "latest": self.receiver.latest,
            "tracks": tracker["tracks"],
            "map": self.receiver.map,
            "age": age,
            "fresh": self.is_fresh(),
            "stale": bool(age is None or age > self.stale_seconds),
            "latency": self.receiver.latency_status(now),
            "error": self.error,
            "backend": "remote-pc",
            "source": self.receiver.last_packet.get("source", "pc"),
            "model": self.receiver.last_packet.get("model"),
            "tracker": {k: v for k, v in tracker.items() if k != "tracks"},
        }
