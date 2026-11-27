"""Remote detection payload validation and latency accounting."""
import math
import threading
import time

from mischief_common.object_geometry import box_metrics, clamp_box, num


class DetectionReceiver:
    def __init__(self):
        self.latest = []
        self.map = []
        self.last_packet = {}
        self.received_at = 0.0
        self._lock = threading.RLock()

    def ingest(self, payload):
        now = time.time()
        packet = dict(payload or {})
        packet.setdefault("source", "pc-yolo")
        packet["received_at"] = now
        detections = []

        for i, item in enumerate(packet.get("detections") or []):
            box = clamp_box(item.get("box"))
            label = str(item.get("label") or item.get("name") or "").strip()
            if not label or not box:
                continue
            score = num(item.get("score", item.get("confidence", 1.0)), 1.0)
            metrics = box_metrics(box)
            detections.append({
                **item,
                "id": item.get("id") or f"{packet.get('frame_id', 'frame')}:{i}",
                "label": label,
                "score": score,
                "box": box,
                **metrics,
                "quality": score * (0.8 if metrics["truncated"] else 1.0),
                "source": packet["source"],
                "model": packet.get("model", item.get("model", "remote")),
                "frame_id": packet.get("frame_id"),
                "captured_at": packet.get("captured_at"),
                "inferred_at": packet.get("inferred_at"),
                "sent_at": packet.get("sent_at"),
                "received_at": now,
            })

        with self._lock:
            self.latest = detections
            self.map = packet.get("map") or []
            self.last_packet = packet
            self.received_at = now
        return packet, detections

    def current(self, now=None):
        """Return copies with age and confidence decayed at read time."""
        now = time.time() if now is None else now
        with self._lock:
            detections = [dict(item) for item in self.latest]
        for item in detections:
            at = item.get("captured_at") or item.get("received_at") or now
            age = max(0.0, now - num(at, now))
            item["age"] = age
            item["quality"] = item.get("quality", item.get("score", 0)) * math.exp(-age / 1.5)
            item["fresh"] = age <= 1.0
        return detections

    def latency_status(self, now=None):
        now = time.time() if now is None else now
        with self._lock:
            p = dict(self.last_packet)
            received_at = self.received_at
        pc = p.get("pc_timing") or {}
        try:
            infer_ms = pc.get("infer_ms")
            roundtrip_ms = pc.get("roundtrip_ms")
            network_ms = None if roundtrip_ms is None or infer_ms is None else round(max(0, roundtrip_ms - infer_ms), 1)
            total_ms = None if not (p.get("captured_at") and received_at) else round((received_at - p["captured_at"]) * 1000, 1)
            return {
                "snapshot_ms": pc.get("capture_to_request_ms"),
                "infer_ms": infer_ms,
                "network_ms": network_ms,
                "roundtrip_ms": roundtrip_ms,
                "total_ms": total_ms,
                "age_on_pi_ms": None if not received_at else round((now - received_at) * 1000, 1),
            }
        except Exception:
            return {}
