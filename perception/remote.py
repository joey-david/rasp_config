"""Remote perception ingest from the PC visual cortex."""
import time

from mischief_common.object_geometry import label_score

from .receiver import DetectionReceiver


class RemotePerception:
    def __init__(self, fresh_seconds=1.0, stale_seconds=10.0):
        self.receiver = DetectionReceiver()
        self.fresh_seconds = fresh_seconds
        self.stale_seconds = stale_seconds
        self.error = ""

    @property
    def detections(self):
        return self.receiver.latest

    @property
    def tracks(self):
        return []

    def start(self):
        pass

    def stop(self):
        pass

    def ingest(self, payload):
        _, detections = self.receiver.ingest(payload)
        self.error = ""
        return self.status()

    def is_fresh(self):
        return bool(self.receiver.received_at and time.time() - self.receiver.received_at <= self.fresh_seconds)

    def best(self, query):
        matches = [(label_score(query, {**d, "age": 0}), d) for d in self.receiver.latest]
        matches = [(s, d) for s, d in matches if s > 0.45]
        return max(matches, key=lambda x: (x[0], x[1].get("score", 0)))[1] if matches else None

    def track(self, track_id):
        return None

    def status(self):
        now = time.time()
        age = None if not self.receiver.received_at else round(now - self.receiver.received_at, 3)
        return {
            "detections": self.receiver.latest,
            "latest": self.receiver.latest,
            "tracks": [],
            "map": self.receiver.map,
            "age": age,
            "fresh": self.is_fresh(),
            "stale": bool(age is None or age > self.stale_seconds),
            "latency": self.receiver.latency_status(now),
            "error": self.error,
            "backend": "remote-pc",
            "source": self.receiver.last_packet.get("source", "pc"),
            "model": self.receiver.last_packet.get("model"),
            "tracker": {"backend": "disabled", "active": 0},
        }
