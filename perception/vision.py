"""Reusable Pi-side vision helpers backed by the PC detector."""
import json
import os
import threading
import time
import urllib.parse
import urllib.request

DETECT_URL = os.getenv("PC_DETECT_URL", "http://192.168.0.24:8081/detect")
VISION_HZ = float(os.getenv("VISION_HZ", "4"))


def box_center_x(box):
    return (float(box[0]) + float(box[2])) * 0.5


def select_target(detections, target=None, last_cx=0.5, continuity_weight=0.35):
    best, best_score = None, -1
    target = target.lower().strip() if target else ""
    for det in detections or []:
        box = det.get("box") or []
        if len(box) != 4:
            continue
        if target and det.get("label", "").lower().strip() != target:
            continue
        score = float(det.get("score") or 0.5) - continuity_weight * abs(box_center_x(box) - last_cx)
        if score > best_score:
            best, best_score = det, score
    return best


def _all_url(detect_url):
    return detect_url.rsplit("/", 1)[0] + "/detect-all"


def _resolve_url(detect_url):
    return detect_url.rsplit("/", 1)[0] + "/resolve-label"


def resolve_label(word, timeout=2.0, detect_url=DETECT_URL):
    url = _resolve_url(detect_url) + "?" + urllib.parse.urlencode({"word": word})
    with urllib.request.urlopen(url, timeout=timeout) as response:
        out = json.loads(response.read().decode())
    if not out.get("ok"):
        raise ValueError(out.get("error") or f"could not resolve {word!r}")
    return out["label"], {"resolve_ms": out.get("resolve_ms"), "resolve_method": out.get("method"), "resolve_score": out.get("score")}


def _post_frame(robot, url, timeout):
    frame, captured_at, frame_id = robot.camera.latest()
    if not frame:
        return None, [], {"error": "no frame"}

    req = urllib.request.Request(url, data=frame, method="POST", headers={
        "Content-Type": "image/jpeg",
        "X-Captured-At": str(captured_at),
        "X-Frame-Id": str(frame_id),
    })
    received_at = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as response:
        out = json.loads(response.read().decode())
    return out, (captured_at, frame_id, received_at), {}


def _ingest(robot, out, timing, source):
    captured_at, frame_id, received_at = timing
    sent_at = time.time()
    detections = out.get("detections") or []
    robot.ingest_detections({
        "source": source, "model": out.get("model"),
        "frame_id": frame_id, "captured_at": captured_at,
        "inferred_at": out.get("inferred_at", sent_at),
        "sent_at": sent_at, "detections": detections,
        "pc_timing": {
            "snapshot_started_at": captured_at, "snapshot_received_at": received_at,
            "infer_done_at": out.get("inferred_at", sent_at), "sent_at": sent_at,
        },
    })
    return detections, {"infer_ms": out.get("infer_ms"), "frame_id": frame_id}


def detect(robot, target, timeout=0.45, detect_url=DETECT_URL):
    url = detect_url + "?" + urllib.parse.urlencode({"label": target})
    out, timing, error = _post_frame(robot, url, timeout)
    if error:
        return [], error
    return _ingest(robot, out, timing, "pc-detect-request")


def detect_all(robot, timeout=0.8, detect_url=DETECT_URL):
    out, timing, error = _post_frame(robot, _all_url(detect_url), timeout)
    if error:
        return [], error
    return _ingest(robot, out, timing, "pc-detect-all")


def detect_target(robot, target_label, last_cx=0.5, timeout=0.45, detect_url=DETECT_URL):
    detections, meta = detect_all(robot, timeout, detect_url)
    return select_target(detections, target_label, last_cx), meta


class VisionScanner:
    def __init__(self, robot, hz=VISION_HZ, timeout=0.8):
        self.robot = robot
        self.hz = max(0.1, float(hz))
        self.timeout = timeout
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        period = 1 / self.hz
        while not self._stop.is_set():
            started = time.time()
            try:
                detect_all(self.robot, timeout=self.timeout)
                self.robot.perception.error = ""
            except Exception as e:
                self.robot.perception.error = str(e)
            self._stop.wait(max(0.0, period - (time.time() - started)))
