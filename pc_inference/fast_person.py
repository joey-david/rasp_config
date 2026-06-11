#!/usr/bin/env python3
"""Fast Apple-Silicon person detector: Pi latest frame -> YOLO -> Pi detections."""
from __future__ import annotations

import argparse
import io
import time


class PersonYolo:
    def __init__(self, model: str, imgsz: int, conf: float, device: str):
        from ultralytics import YOLO
        import torch

        self.model, self.imgsz, self.conf = YOLO(model), imgsz, conf
        self.device = device or ("mps" if torch.backends.mps.is_available() else "cpu")

    def detect(self, jpg: bytes):
        from PIL import Image

        img = Image.open(io.BytesIO(jpg)).convert("RGB")
        w, h = img.size
        result = self.model.predict(
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


def grab_frame(pi: str):
    import requests

    t0 = time.time()
    r = requests.get(f"{pi}/frame/latest.jpg", timeout=1.0)
    r.raise_for_status()
    return r.content, float(r.headers.get("X-Captured-At") or time.time()), t0, time.time()


def post(pi: str, detections, frame_id, captured_at, timing, model):
    import requests

    payload = {
        "source": "mac-person-yolo", "model": model, "frame_id": frame_id,
        "captured_at": captured_at, "inferred_at": timing["infer_done_at"],
        "sent_at": time.time(), "detections": detections, "pc_timing": timing,
    }
    r = requests.post(f"{pi}/api/perception/detections", json=payload, timeout=0.6)
    r.raise_for_status()
    return r.json()


def run(args):
    pi = args.pi.rstrip("/")
    det = PersonYolo(args.model, args.imgsz, args.conf, args.device)
    period = 1 / max(1, args.hz)
    frame_id = 0
    print(f"person detector model={args.model} device={det.device} imgsz={args.imgsz}", flush=True)
    while not args.frames or frame_id < args.frames:
        start = time.time()
        try:
            jpg, captured_at, t0, t1 = grab_frame(pi)
            detections = det.detect(jpg)
            t2 = time.time()
            timing = {"snapshot_started_at": t0, "snapshot_received_at": t1,
                      "infer_done_at": t2, "sent_at": time.time()}
            state = post(pi, detections, frame_id, captured_at, timing, args.model)
            lat = (state.get("latency") or {}).get("infer_ms")
            labels = ",".join(f"{d['score']:.2f}" for d in detections) or "none"
            print(f"frame={frame_id} n={len(detections)} infer={lat}ms scores={labels}", flush=True)
            frame_id += 1
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"person detector retry: {e}", flush=True)
        time.sleep(max(0, period - (time.time() - start)))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--pi", default="http://192.168.0.43:8080")
    p.add_argument("--model", default="yolo11n.pt")
    p.add_argument("--imgsz", type=int, default=320)
    p.add_argument("--conf", type=float, default=0.25)
    p.add_argument("--hz", type=float, default=15)
    p.add_argument("--device", default="")
    p.add_argument("--frames", type=int, default=0)
    run(p.parse_args())


if __name__ == "__main__":
    main()
