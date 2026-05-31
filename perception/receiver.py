"""Remote detection payload validation and latency accounting."""
import time

from mischief_common.object_geometry import clamp_box, num


class DetectionReceiver:
    def __init__(self):
        self.latest = []
        self.map = []
        self.last_packet = {}
        self.received_at = 0.0

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
            detections.append({
                **item,
                "id": item.get("id") or f"{packet.get('frame_id', 'frame')}:{i}",
                "label": label,
                "score": num(item.get("score", item.get("confidence", 1.0)), 1.0),
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
        return packet, detections

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
            network_ms = None if not (sent and self.received_at) else round(max(0, self.received_at - sent) * 1000, 1)
            infer_ms = None if not (got and inferred) else round((inferred - got) * 1000, 1)
            total_ms = None if not (p.get("captured_at") and self.received_at) else round((self.received_at - p["captured_at"]) * 1000, 1)
            return {
                "snapshot_ms": None if not (started and got) else round((got - started) * 1000, 1),
                "infer_ms": infer_ms,
                "network_ms": network_ms,
                "post_clock_skew_ms": network_ms,
                "total_ms": total_ms,
                "age_on_pi_ms": None if not self.received_at else round((now - self.received_at) * 1000, 1),
            }
        except Exception:
            return {}
