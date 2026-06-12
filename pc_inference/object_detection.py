#!/usr/bin/env python3
"""Tiny PC object detector: POST /detect?label=<COCO label> with a JPEG."""
from __future__ import annotations

import argparse
import io
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from resolve_label import LabelResolver


class ObjectYolo:
    def __init__(self, model, imgsz, conf, device):
        from ultralytics import YOLO
        import torch

        self.model, self.imgsz, self.conf = model, imgsz, conf
        self.net = YOLO(model)
        items = self.net.names.items() if isinstance(self.net.names, dict) else enumerate(self.net.names)
        self.names = {int(i): name for i, name in items}
        self.resolver = LabelResolver(self.names)
        self.class_ids = {name.lower(): i for i, name in self.names.items()}
        self.device = device or ("mps" if torch.backends.mps.is_available() else "cpu")

    def class_id(self, label):
        resolved, _, _ = self.resolver.resolve(label)
        return self.class_ids[resolved]

    def _detections(self, result, width, height):
        detections = []
        for box in result.boxes:
            x1, y1, x2, y2 = [float(x) for x in box.xyxy[0]]
            label = self.names[int(box.cls[0])]
            cx = round((x1 + x2) / (2 * width), 2)
            detections.append({
                "id": f"{label}:{cx}",
                "label": label,
                "score": round(float(box.conf[0]), 3),
                "box": [x1 / width, y1 / height, x2 / width, y2 / height],
            })
        return detections

    def detect(self, jpg, label=None):
        from PIL import Image

        img = Image.open(io.BytesIO(jpg)).convert("RGB")
        w, h = img.size
        class_id = None if label is None else self.class_id(label)
        result = self.net.predict(
            img, classes=None if class_id is None else [class_id], imgsz=self.imgsz, conf=self.conf,
            device=self.device, verbose=False,
        )[0]
        return ("all" if class_id is None else self.names[class_id]), self._detections(result, w, h)


def json_response(handler, code, payload):
    body = json.dumps(payload).encode()
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def serve(args):
    detector = ObjectYolo(args.model, args.imgsz, args.conf, args.device)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/resolve-label":
                return self.resolve_label(parsed)
            if parsed.path != "/health":
                return self.send_error(404)
            json_response(self, 200, {
                "ok": True, "model": detector.model, "device": detector.device,
                "imgsz": detector.imgsz, "labels": list(detector.class_ids),
            })

        def resolve_label(self, parsed, word=None):
            word = word if word is not None else (
                parse_qs(parsed.query).get("word") or parse_qs(parsed.query).get("label") or [""]
            )[0]
            started = time.perf_counter()
            try:
                label, method, score = detector.resolver.resolve(word)
                json_response(self, 200, {
                    "ok": True, "input": word, "label": label, "method": method,
                    "score": score, "resolve_ms": round((time.perf_counter() - started) * 1000, 3),
                })
            except ValueError as e:
                json_response(self, 400, {"ok": False, "error": str(e)})

        def do_POST(self):
            parsed = urlparse(self.path)
            if parsed.path == "/resolve-label":
                body = self.rfile.read(int(self.headers.get("Content-Length", "0") or 0)).decode().strip()
                word = body
                if self.headers.get("Content-Type", "").startswith("application/json"):
                    word = json.loads(body or "{}").get("word", "")
                return self.resolve_label(parsed, word)
            if parsed.path not in ("/detect", "/detect-all"):
                return self.send_error(404)
            raw_label = None if parsed.path == "/detect-all" else (parse_qs(parsed.query).get("label") or ["person"])[0]
            jpg = self.rfile.read(int(self.headers.get("Content-Length", "0") or 0))
            started = time.time()
            try:
                label, detections = detector.detect(jpg, raw_label)
                json_response(self, 200, {
                    "ok": True, "label": label, "model": detector.model, "device": detector.device,
                    "detections": detections, "inferred_at": time.time(),
                    "infer_ms": round((time.time() - started) * 1000, 1),
                })
            except ValueError as e:
                json_response(self, 400, {"ok": False, "error": str(e), "detections": []})
            except Exception as e:
                json_response(self, 500, {"ok": False, "error": str(e), "detections": []})

    print(f"detect server http://{args.host}:{args.port} model={args.model} device={detector.device}", flush=True)
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument("--model", default="yolo26n.pt")
    parser.add_argument("--imgsz", type=int, default=320)
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--device", default="")
    serve(parser.parse_args())


if __name__ == "__main__":
    main()
