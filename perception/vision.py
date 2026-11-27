"""Reusable Pi-side vision helpers backed by the PC detector."""
from contextlib import contextmanager
import json
import io
import os
import threading
import time
import urllib.parse
import urllib.request

from PIL import Image

from mischief_common.object_geometry import box_metrics

DETECT_URL = os.getenv("PC_DETECT_URL", "http://192.168.0.24:8081/detect")
VISION_HZ = float(os.getenv("VISION_HZ", "4"))
MAX_DETECT_IMGSZ = int(os.getenv("MAX_DETECT_IMGSZ", "1920"))
_INFERENCE_LOCK = threading.RLock()


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


def _jpeg_size(frame):
    try:
        img = Image.open(io.BytesIO(frame))
        return f"{img.size[0]}x{img.size[1]}"
    except Exception:
        return None


def _post_jpeg(robot, url, timeout, frame, captured_at, frame_id):
    if not frame:
        return None, [], {"error": "no frame"}
    image_size = _jpeg_size(frame)

    req = urllib.request.Request(url, data=frame, method="POST", headers={
        "Content-Type": "image/jpeg",
        "X-Captured-At": str(captured_at),
        "X-Frame-Id": str(frame_id),
    })
    request_started = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as response:
        out = json.loads(response.read().decode())
    request_done = time.time()
    if image_size:
        out["image_size"] = image_size
    return out, (captured_at, frame_id, request_started, request_done), {}


def _post_frame(robot, url, timeout):
    _, _, previous_id = robot.camera.latest()
    frame, captured_at, frame_id = robot.camera.snapshot_with_meta(
        timeout=min(1.0, max(0.2, timeout)), after_frame_id=previous_id
    )
    if not frame or frame_id <= previous_id:
        return None, [], {"error": "no fresh camera frame"}
    return _post_jpeg(robot, url, timeout, frame, captured_at, frame_id)


def _post_maximum_frame(robot, url, timeout):
    frame, captured_at, frame_id = robot.camera.maximum_snapshot()
    return _post_jpeg(robot, url, timeout, frame, captured_at, frame_id)


def _ingest(robot, out, timing, source):
    captured_at, frame_id, request_started, request_done = timing
    sent_at = time.time()
    detections = out.get("detections") or []
    robot.ingest_detections({
        "source": source, "model": out.get("model"),
        "frame_id": frame_id, "captured_at": captured_at,
        "inferred_at": out.get("inferred_at", sent_at),
        "sent_at": sent_at, "detections": detections,
        "pc_timing": {
            "capture_to_request_ms": round(max(0, request_started - captured_at) * 1000, 1),
            "roundtrip_ms": round(max(0, request_done - request_started) * 1000, 1),
            "infer_ms": out.get("infer_ms"),
        },
    })
    return detections, {"infer_ms": out.get("infer_ms"), "frame_id": frame_id, "image_size": out.get("image_size")}


def detect(robot, target, timeout=0.45, detect_url=DETECT_URL):
    url = detect_url + "?" + urllib.parse.urlencode({"label": target})
    with _INFERENCE_LOCK:
        out, timing, error = _post_frame(robot, url, timeout)
    if error:
        return [], error
    return _ingest(robot, out, timing, "pc-detect-request")


def detect_all(robot, timeout=0.8, detect_url=DETECT_URL):
    with _INFERENCE_LOCK:
        out, timing, error = _post_frame(robot, _all_url(detect_url), timeout)
    if error:
        return [], error
    return _ingest(robot, out, timing, "pc-detect-all")


def capture_detect_all(robot, timeout=2.0, detect_url=DETECT_URL):
    """Capture once, detect that JPEG, and return the same JPEG for planning."""
    with _INFERENCE_LOCK:
        _, _, previous_id = robot.camera.latest()
        frame, captured_at, frame_id = robot.camera.snapshot_with_meta(
            timeout=min(2.0, max(0.2, timeout)), after_frame_id=previous_id
        )
        if not frame or frame_id <= previous_id:
            raise RuntimeError("no fresh camera frame")
        out, timing, error = _post_jpeg(
            robot, _all_url(detect_url), timeout, frame, captured_at, frame_id
        )
    if error:
        raise RuntimeError(error.get("error", "detection failed"))
    detections, meta = _ingest(robot, out, timing, "pc-coordinated-observation")
    return frame, detections, meta


def detect_target(robot, target_label, last_cx=0.5, timeout=0.45, detect_url=DETECT_URL):
    detections, meta = detect(robot, target_label, timeout, detect_url)
    return select_target(detections, target_label, last_cx), meta


def detect_target_maximum(robot, target_label, last_cx=0.5, timeout=12.0, detect_url=DETECT_URL, imgsz=MAX_DETECT_IMGSZ):
    url = detect_url + "?" + urllib.parse.urlencode({"label": target_label, "imgsz": int(imgsz)})
    with _INFERENCE_LOCK:
        out, timing, error = _post_maximum_frame(robot, url, timeout)
    if error:
        return None, error
    detections, meta = _ingest(robot, out, timing, "pc-detect-maximum")
    return select_target(detections, target_label, last_cx), {**meta, "snapshot": "maximum", "imgsz": imgsz}


def detect_target_samples(
    robot,
    target_label,
    last_cx=0.5,
    attempts=3,
    timeout=2.0,
    maximum=False,
):
    """Localize a target from independent fresh frames and return median cx."""
    found, metadata = [], []
    detector = detect_target_maximum if maximum else detect_target
    with _INFERENCE_LOCK:
        for _ in range(max(1, int(attempts))):
            try:
                det, meta = detector(robot, target_label, last_cx, timeout)
            except Exception as exc:
                det, meta = None, {"error": str(exc)}
            metadata.append(meta)
            if det:
                found.append({**det, **box_metrics(det["box"])})
                last_cx = box_center_x(det["box"])
    if not found:
        errors = [m.get("error") for m in metadata if m.get("error")]
        return None, {
            "attempts": len(metadata),
            "confirmations": 0,
            "error": errors[-1] if errors else "target not detected",
        }
    ordered = sorted(found, key=lambda d: box_center_x(d["box"]))
    chosen = ordered[len(ordered) // 2]
    centers = [box_center_x(d["box"]) for d in found]
    return chosen, {
        **metadata[-1],
        "attempts": len(metadata),
        "confirmations": len(found),
        "cx_spread": round(max(centers) - min(centers), 4),
    }


def detect_pair_samples(robot, source_label, destination_label, attempts=3, timeout=1.0):
    """Observe two labels in the same fresh frames for image-relative steering."""
    pairs, metadata = [], []
    with _INFERENCE_LOCK:
        for _ in range(max(1, int(attempts))):
            try:
                detections, meta = detect_all(robot, timeout)
            except Exception as exc:
                detections, meta = [], {"error": str(exc)}
            metadata.append(meta)
            source = select_target(detections, source_label)
            destination = select_target(detections, destination_label)
            if source and destination:
                pairs.append((
                    {**source, **box_metrics(source["box"])},
                    {**destination, **box_metrics(destination["box"])},
                ))
    if not pairs:
        return None, None, {
            "attempts": len(metadata),
            "confirmations": 0,
            "error": next((m.get("error") for m in reversed(metadata) if m.get("error")), "pair not detected"),
        }
    pairs.sort(key=lambda pair: box_center_x(pair[0]["box"]))
    source, destination = pairs[len(pairs) // 2]
    return source, destination, {
        **metadata[-1], "attempts": len(metadata), "confirmations": len(pairs)
    }


class VisionScanner:
    def __init__(self, robot, hz=VISION_HZ, timeout=0.8):
        self.robot = robot
        self.hz = max(0.1, float(hz))
        self.timeout = timeout
        self._stop = threading.Event()
        self._thread = None
        self._pause_lock = threading.Lock()
        self._pause_count = 0

    @contextmanager
    def exclusive(self):
        """Pause background scanning while an active skill owns perception."""
        with self._pause_lock:
            self._pause_count += 1
            outermost = self._pause_count == 1
        if outermost:
            print("[perception] active skill acquired exclusive inference", flush=True)
        try:
            with _INFERENCE_LOCK:
                yield
        finally:
            with self._pause_lock:
                self._pause_count -= 1
                resumed = self._pause_count == 0
            if resumed:
                print("[perception] background scanner resumed", flush=True)

    def _paused(self):
        with self._pause_lock:
            return self._pause_count > 0

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
            if self._paused():
                self._stop.wait(0.05)
                continue
            started = time.time()
            try:
                detect_all(self.robot, timeout=self.timeout)
                self.robot.perception.error = ""
            except Exception as e:
                self.robot.perception.error = str(e)
            self._stop.wait(max(0.0, period - (time.time() - started)))
