"""Remote perception ingest from the PC visual cortex."""
import time


def _num(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return default


def _box(raw):
    vals = list(raw or (0, 0, 0, 0))[:4]
    vals += [0] * (4 - len(vals))
    x1, y1, x2, y2 = [_num(v) for v in vals]
    if max(x1, y1, x2, y2) > 1.5:
        return None
    x1, x2 = sorted((max(0, min(1, x1)), max(0, min(1, x2))))
    y1, y2 = sorted((max(0, min(1, y1)), max(0, min(1, y2))))
    return (x1, y1, x2, y2)


class RemotePerception:
    def __init__(self, memory=None, fresh_seconds=1.0, stale_seconds=10.0):
        self.memory = memory
        self.fresh_seconds = fresh_seconds
        self.stale_seconds = stale_seconds
        self.latest = []
        self.map = []
        self.last_packet = {}
        self.error = ""
        self.received_at = 0.0

    def start(self): pass

    def stop(self): pass

    def ingest(self, payload):
        now = time.time()
        packet = dict(payload or {})
        packet.setdefault("source", "pc")
        packet["received_at"] = now
        detections = []

        for i, item in enumerate(packet.get("detections") or []):
            box = _box(item.get("box"))
            label = str(item.get("label") or item.get("name") or "").strip()
            if not label or not box:
                continue
            detections.append({
                **item,
                "id": item.get("id") or f"{packet.get('frame_id', 'frame')}:{i}",
                "label": label,
                "score": _num(item.get("score", item.get("confidence", 1.0)), 1.0),
                "box": box,
                "source": packet["source"],
                "model": packet.get("model", item.get("model", "remote")),
                "frame_id": packet.get("frame_id"),
                "captured_at": packet.get("captured_at"),
                "inferred_at": packet.get("inferred_at"),
                "sent_at": packet.get("sent_at"),
                "received_at": now,
            })

        self.latest = detections
        self.map = packet.get("map") or []
        self.last_packet = packet
        self.received_at = now
        self.error = ""
        if self.memory:
            self.memory.update(detections)
        return self.status()

    def is_fresh(self):
        return bool(self.received_at and time.time() - self.received_at <= self.fresh_seconds)

    def status(self):
        now = time.time()
        age = None if not self.received_at else round(now - self.received_at, 3)
        return {
            "detections": self.latest,
            "latest": self.latest,
            "map": self.map,
            "age": age,
            "fresh": self.is_fresh(),
            "stale": bool(age is None or age > self.stale_seconds),
            "latency": self.latency_status(now),
            "error": self.error,
            "backend": "remote-pc",
            "source": self.last_packet.get("source", "pc"),
            "model": self.last_packet.get("model"),
        }

    def latency_status(self, now=None):
        now = now or time.time()
        p = self.last_packet
        pc = p.get("pc_timing") or {}
        started, got, inferred, sent = (
            pc.get("snapshot_started_at"),
            pc.get("snapshot_received_at"),
            pc.get("infer_done_at"),
            pc.get("sent_at"),
        )
        try:
            return {
                "snapshot_ms": None if not (started and got) else round((got - started) * 1000, 1),
                "infer_ms": None if not (got and inferred) else round((inferred - got) * 1000, 1),
                "post_clock_skew_ms": None if not (sent and self.received_at) else round((self.received_at - sent) * 1000, 1),
                "age_on_pi_ms": None if not self.received_at else round((now - self.received_at) * 1000, 1),
            }
        except Exception:
            return {}
