#!/usr/bin/env python3
"""Tiny PC detector service: POST /detect?label=person with a JPEG, get boxes."""
from __future__ import annotations

import argparse
import io
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


class EdgeHold:
    def __init__(self, edge=0.04, hold_s=1.0, needed=2):
        self.edge, self.hold_s, self.needed = edge, hold_s, needed
        self.state = {}

    def _side(self, box):
        if box[0] <= self.edge:
            return "left"
        if box[2] >= 1.0 - self.edge:
            return "right"
        return None

    def _edge_box(self, det, side):
        x1, y1, x2, y2 = det["box"]
        w = max(0.04, min(0.35, x2 - x1))
        if side == "left":
            x1, x2 = 0.0, w
        else:
            x1, x2 = 1.0 - w, 1.0
        return [x1, y1, x2, y2]

    def apply(self, label, detections):
        now = time.time()
        label = label.lower()
        label_dets = [d for d in detections if d.get("label", "").lower() == label]
        seen_edges = set()
        for det in label_dets:
            side = self._side(det.get("box") or [])
            if not side:
                continue
            key = (label, side)
            st = self.state.get(key, {"streak": 0})
            st = {"streak": st["streak"] + 1, "last": now, "det": det}
            self.state[key] = st
            seen_edges.add(side)
        for key, st in list(self.state.items()):
            if key[0] == label and now - st.get("last", 0) > self.hold_s:
                del self.state[key]
        if label_dets:
            return detections
        held = []
        for (held_label, side), st in self.state.items():
            if held_label != label or side in seen_edges or st.get("streak", 0) < self.needed:
                continue
            if now - st["last"] <= self.hold_s:
                det = dict(st["det"])
                det["id"] = f"{label}:held-{side}"
                det["score"] = min(float(det.get("score") or 0.5), 0.2)
                det["box"] = self._edge_box(det, side)
                det["held_edge"] = side
                det["held_age"] = round(now - st["last"], 3)
                held.append(det)
        return detections + held


class PersonYolo:
    def __init__(self, model: str, imgsz: int, conf: float, device: str):
        from ultralytics import YOLO
        import torch

        self.name, self.imgsz, self.conf = model, imgsz, conf
        self.net = YOLO(model)
        self.device = device or ("mps" if torch.backends.mps.is_available() else "cpu")

    def detect(self, jpg: bytes, label: str):
        if label.lower() not in {"person", "people", "human"}:
            return []
        from PIL import Image

        img = Image.open(io.BytesIO(jpg)).convert("RGB")
        w, h = img.size
        result = self.net.predict(
            img, classes=[0], imgsz=self.imgsz, conf=self.conf,
            device=self.device, verbose=False,
        )[0]
        out = []
        for b in result.boxes:
            x1, y1, x2, y2 = [float(x) for x in b.xyxy[0]]
            score = float(b.conf[0])
            out.append({
                "id": f"person:{round((x1 + x2) / (2 * w), 2)}",
                "label": "person", "score": round(score, 3),
                "box": [x1 / w, y1 / h, x2 / w, y2 / h],
            })
        return out


def serve(args):
    detector = PersonYolo(args.model, args.imgsz, args.conf, args.device)
    edge_hold = EdgeHold(args.edge_hold_margin, args.edge_hold_seconds, args.edge_hold_frames)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a): pass

        def send_json(self, code, obj):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if urlparse(self.path).path == "/health":
                return self.send_json(200, {
                    "ok": True, "model": detector.name,
                    "device": detector.device, "imgsz": detector.imgsz,
                })
            self.send_error(404)

        def do_POST(self):
            u = urlparse(self.path)
            if u.path != "/detect":
                return self.send_error(404)
            label = (parse_qs(u.query).get("label") or ["person"])[0]
            n = int(self.headers.get("Content-Length", "0") or 0)
            jpg = self.rfile.read(n)
            t0 = time.time()
            try:
                detections = edge_hold.apply(label, detector.detect(jpg, label))
                self.send_json(200, {
                    "ok": True, "label": label, "model": detector.name,
                    "device": detector.device, "detections": detections,
                    "inferred_at": time.time(), "infer_ms": round((time.time() - t0) * 1000, 1),
                })
            except Exception as e:
                self.send_json(500, {"ok": False, "error": str(e), "detections": []})

    print(f"detect server http://{args.host}:{args.port} model={args.model} device={detector.device}", flush=True)
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8081)
    p.add_argument("--model", default="yolo11n.pt")
    p.add_argument("--imgsz", type=int, default=320)
    p.add_argument("--conf", type=float, default=0.25)
    p.add_argument("--device", default="")
    p.add_argument("--edge-hold-margin", type=float, default=0.04)
    p.add_argument("--edge-hold-seconds", type=float, default=1.0)
    p.add_argument("--edge-hold-frames", type=int, default=2)
    serve(p.parse_args())


if __name__ == "__main__":
    main()
