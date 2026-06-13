"""Small frame sources for odometry calibration scripts."""

import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import cv2
import numpy as np


def run_dir(kind, out_dir=None):
    root = Path(out_dir or "calibrations/odometry")
    path = root / f"{kind}-{time.strftime('%Y%m%d-%H%M%S')}"
    (path / "frames").mkdir(parents=True, exist_ok=True)
    return path


def frame_path(path, frame):
    return path / "frames" / f"{frame:06d}.jpg"


class DriveCommand:
    def __init__(self, linear=None, angular=None, countdown=3, refresh_seconds=0.25):
        self.linear = linear
        self.angular = angular
        self.countdown = countdown
        self.refresh_seconds = refresh_seconds
        self.robot = None
        self._last_sent = 0.0

    @property
    def active(self):
        return self.linear is not None or self.angular is not None

    def _command(self):
        linear = 0 if self.linear is None else self.linear
        angular = 0 if self.angular is None else self.angular
        return linear, angular

    def start(self):
        if not self.active:
            return
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from robot_api import robot

        self.robot = robot
        for i in range(int(self.countdown), 0, -1):
            print(f"driving in {i}...", flush=True)
            time.sleep(1)

        linear, angular = self._command()
        print(f"set_velocity linear={linear:g} angular={angular:g}", flush=True)
        self.refresh(force=True)

    def refresh(self, force=False):
        if self.robot is None:
            return
        now = time.time()
        if not force and now - self._last_sent < self.refresh_seconds:
            return
        linear, angular = self._command()
        self.robot.set_velocity(linear, angular, source="odometry-calibration")
        self._last_sent = now

    def stop(self):
        if self.robot is not None:
            print("stopping robot", flush=True)
            self.robot.stop(source="odometry-calibration")


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
            frame = bytes(buf[start : end + 2])
            del buf[: end + 2]
            yield frame


def rpicam_gray_frames(width=160, height=120, fps=30):
    cmd = [
        "rpicam-vid",
        "-n",
        "--codec",
        "mjpeg",
        "--width",
        str(max(width, 160)),
        "--height",
        str(max(height, 120)),
        "--framerate",
        str(int(fps)),
        "--timeout",
        "0",
        "--output",
        "-",
    ]
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True
    )
    try:
        for jpg in jpeg_frames(proc.stdout):
            arr = np.frombuffer(jpg, dtype=np.uint8)
            gray = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
            if gray is None:
                continue
            yield cv2.resize(gray, (width, height), interpolation=cv2.INTER_AREA), time.time()
    finally:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.communicate(timeout=1)
        except Exception:
            pass


def gray_frames(camera=None, frames_dir=None, width=160, height=120, fps=30):
    if frames_dir:
        paths = sorted(Path(frames_dir).glob("*"))
        t0 = time.time()
        for i, path in enumerate(paths, start=1):
            img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            if img is None:
                continue
            now = t0 + i / max(1, fps)
            yield cv2.resize(img, (width, height), interpolation=cv2.INTER_AREA), now
        return

    if camera in {None, "rpicam", "picam"}:
        yield from rpicam_gray_frames(width, height, fps)
        return

    source = int(camera) if str(camera).isdigit() else camera
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        raise SystemExit(f"could not open camera/source: {camera!r}")
    try:
        period = 1.0 / max(1, fps)
        next_at = time.time()
        while True:
            now = time.time()
            if now < next_at:
                time.sleep(next_at - now)
            t = time.time()
            ok, frame = cap.read()
            if not ok:
                break
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            yield cv2.resize(gray, (width, height), interpolation=cv2.INTER_AREA), t
            next_at = t + period
    finally:
        cap.release()
