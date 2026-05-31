"""Raw camera service: rpicam process, MJPEG frames, snapshots."""
import io, os, signal, subprocess, threading, time
from PIL import Image

try:
    import cv2
    import numpy as np
except Exception:  # keep camera usable without tracker deps
    cv2 = np = None

WIDTH = int(os.getenv("CAMERA_WIDTH", 1296))
HEIGHT = int(os.getenv("CAMERA_HEIGHT", 972))
FPS = int(os.getenv("CAMERA_FPS", 30))
MODE = os.getenv("CAMERA_MODE", "").strip()
GRAY_SIZE = (320, 240)


def clamp(v, lo, hi, default):
    try: return max(lo, min(hi, int(v)))
    except Exception: return default


def yes(v, default=False):
    return default if v is None else str(v).lower() in {"1", "true", "yes", "on"}


def jpeg_frames(stream):
    buf = bytearray()
    while True:
        chunk = stream.read(8192)
        if not chunk:
            return
        buf.extend(chunk)
        while True:
            start = buf.find(b"\xff\xd8")
            if start < 0:
                if len(buf) > 1024 * 1024:
                    del buf[:-2]
                break
            end = buf.find(b"\xff\xd9", start + 2)
            if end < 0:
                if start > 0:
                    del buf[:start]
                break
            frame = bytes(buf[start:end + 2])
            del buf[:end + 2]
            yield frame


class Camera:
    def __init__(self):
        self.settings = {"fps": clamp(FPS, 1, 30, 30), "hflip": False, "vflip": False, "crop": 0}
        self.frame, self.frame_at, self.error = None, 0, ""
        self.gray, self.gray_at, self._gray_source_at = None, 0, 0
        self._version = 0
        self._cv = threading.Condition()
        self._stop = threading.Event()

    def start(self):
        threading.Thread(target=self._worker, daemon=True).start()

    def stop(self):
        self._stop.set()
        with self._cv: self._cv.notify_all()

    def apply_settings(self, **kw):
        with self._cv:
            old = self.settings.copy()
            self.settings |= {
                "fps": clamp(kw.get("fps", old["fps"]), 1, 30, old["fps"]),
                "hflip": yes(kw.get("hflip"), old["hflip"]),
                "vflip": yes(kw.get("vflip"), old["vflip"]),
                "crop": clamp(kw.get("crop", old["crop"]), 0, 75, old["crop"]),
            }
            if any(old[k] != self.settings[k] for k in ("fps", "hflip", "vflip")):
                self._version += 1
            self._cv.notify_all()
        return self.status()

    def cmd(self, s):
        cmd = [
            "rpicam-vid", "-n", "--codec", "mjpeg",
            "--width", str(WIDTH), "--height", str(HEIGHT),
            "--framerate", str(s["fps"]),
            "--timeout", "0", "--output", "-",
        ]
        if MODE: cmd += ["--mode", MODE]
        if s["hflip"]: cmd += ["--hflip"]
        if s["vflip"]: cmd += ["--vflip"]
        return cmd

    def crop(self, frame):
        p = self.settings["crop"]
        if p <= 0: return frame
        try:
            img = Image.open(io.BytesIO(frame)).convert("RGB")
            w, h = img.size
            keep = max(.25, 1 - p / 100)
            nw, nh = int(w * keep), int(h * keep)
            x, y = (w - nw) // 2, (h - nh) // 2
            out = io.BytesIO()
            img.crop((x, y, x + nw, y + nh)).save(out, "JPEG", quality=90)
            return out.getvalue()
        except Exception:
            return frame

    def make_gray(self, frame):
        if not (frame and cv2 and np):
            return None
        arr = np.frombuffer(frame, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
        if img is None:
            return None
        return cv2.resize(img, GRAY_SIZE, interpolation=cv2.INTER_AREA)

    def _worker(self):
        while not self._stop.is_set():
            with self._cv:
                version, settings = self._version, self.settings.copy()
            proc = subprocess.Popen(self.cmd(settings), stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
            try:
                for frame in jpeg_frames(proc.stdout):
                    if self._stop.is_set() or version != self._version:
                        break
                    cropped = self.crop(frame)
                    with self._cv:
                        self.frame, self.frame_at, self.error = cropped, time.time(), ""
                        self._cv.notify_all()
            except Exception as e:
                with self._cv: self.error = str(e)
            finally:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                    _, err = proc.communicate(timeout=1)
                    if err and not self._stop.is_set():
                        with self._cv: self.error = err.decode("utf-8", "replace")[-1000:]
                except Exception:
                    pass
            time.sleep(.3)

    def snapshot(self, timeout=5):
        end = time.time() + timeout
        with self._cv:
            seen = self.frame_at
            while time.time() < end:
                if self.frame and self.frame_at != seen:
                    return self.frame
                self._cv.wait(max(.1, end - time.time()))
            return self.frame

    def gray_snapshot(self, timeout=5):
        end = time.time() + timeout
        while time.time() < end:
            with self._cv:
                frame, frame_at = self.frame, self.frame_at
                if frame and frame_at != self._gray_source_at:
                    break
                self._cv.wait(min(.1, max(0, end - time.time())))
        else:
            return self.gray, self.gray_at
        gray = self.make_gray(frame)
        with self._cv:
            if gray is not None and frame_at >= self._gray_source_at:
                self.gray, self.gray_at, self._gray_source_at = gray, frame_at, frame_at
            return self.gray, self.gray_at

    def frames(self):
        seen = 0
        while not self._stop.is_set():
            with self._cv:
                while self.frame_at == seen and not self._stop.is_set():
                    self._cv.wait(10)
                seen, frame = self.frame_at, self.frame
            if frame:
                yield frame

    def status(self):
        return {
            "settings": self.settings.copy(),
            "age": None if not self.frame_at else round(time.time() - self.frame_at, 2),
            "gray": bool(self.gray_at),
            "error": self.error,
            "size": f"{WIDTH}x{HEIGHT}",
        }
