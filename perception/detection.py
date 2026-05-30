"""CPU-only object detector using OpenCV DNN MobileNet-SSD."""
from dataclasses import dataclass, asdict
from pathlib import Path
import threading, time
import cv2
import numpy as np
from PIL import Image
import io

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "perception" / "models"
PROTO = MODEL_DIR / "MobileNetSSD_deploy.prototxt"
MODEL = MODEL_DIR / "MobileNetSSD_deploy.caffemodel"

CLASSES = [
    "background", "aeroplane", "bicycle", "bird", "boat", "bottle", "bus",
    "car", "cat", "chair", "cow", "dining table", "dog", "horse",
    "motorbike", "person", "potted plant", "sheep", "sofa", "train",
    "tv monitor",
]


@dataclass
class Detection:
    label: str
    score: float
    box: tuple

    @property
    def confidence(self):
        return self.score

    def dict(self):
        return asdict(self)

class Detector:
    def __init__(self, camera, memory=None, every=0.05, threshold=0.45):
        self.camera = camera
        self.memory = memory
        self.every = every
        self.threshold = threshold
        self.latest = []
        self.error = ""
        self._stop = threading.Event()
        self._thread = None
        self.net = cv2.dnn.readNetFromCaffe(str(PROTO), str(MODEL))

    def start(self):
        if not self._thread:
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()

    def _decode_jpeg(self, jpeg):
        arr = np.asarray(Image.open(io.BytesIO(jpeg)).convert("RGB"))
        return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)

    def detect(self, jpeg):
        img = self._decode_jpeg(jpeg)
        h, w = img.shape[:2]
        blob = cv2.dnn.blobFromImage(
            cv2.resize(img, (300, 300)),
            0.007843,
            (300, 300),
            127.5,
        )
        self.net.setInput(blob)
        out = self.net.forward()

        detections = []
        for i in range(out.shape[2]):
            conf = float(out[0, 0, i, 2])
            if conf < self.threshold:
                continue

            idx = int(out[0, 0, i, 1])
            if idx >= len(CLASSES):
                continue

            x1, y1, x2, y2 = out[0, 0, i, 3:7]
            box = (
                max(0.0, min(1.0, float(x1))),
                max(0.0, min(1.0, float(y1))),
                max(0.0, min(1.0, float(x2))),
                max(0.0, min(1.0, float(y2))),
            )
            detections.append(Detection(CLASSES[idx], round(conf, 3), box))

        return detections

    def _loop(self):
        while not self._stop.is_set():
            frame = self.camera.snapshot(timeout=1)
            if frame:
                try:
                    self.latest = self.detect(frame)
                    self.error = ""
                    if self.memory:
                        self.memory.update(self.latest)
                except Exception as e:
                    self.error = str(e)
            time.sleep(self.every)
    
    def status(self):
        detections = [d.dict() for d in self.latest]
        return {
            "detections": detections,
            "latest": detections,
            "error": self.error,
            "backend": "opencv-dnn-mobilenet-ssd",
        }