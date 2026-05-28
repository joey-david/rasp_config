#!/usr/bin/env python3
import html
import io
import os
import signal
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

import numpy as np
from PIL import Image

RECORD_DIR = Path(os.environ.get("CAMERA_RECORD_DIR", "/home/joey/camera-recordings"))
WIDTH = int(os.environ.get("CAMERA_WIDTH", "1296"))
HEIGHT = int(os.environ.get("CAMERA_HEIGHT", "972"))
FPS = int(os.environ.get("CAMERA_FPS", "30"))
RECORD_DIR.mkdir(parents=True, exist_ok=True)
FFMPEG = shutil.which("ffmpeg")

state_lock = threading.Lock()
state_cv = threading.Condition(state_lock)

settings = {
    "hflip": True,
    "vflip": True,
    "dewarp_strength": 0,
    "preview_fps": FPS,
    "audio_gain_db": int(os.environ.get("CAMERA_AUDIO_GAIN_DB", "24")),
}
settings_version = 0
latest_frame = None
latest_frame_at = 0.0
latest_error = ""
remap_cache = {}
record_session = None
stop_event = threading.Event()
AUDIO_DEVICE = None
AUDIO_STATUS = "not detected"


def run(cmd, timeout=15):
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)


def rpicam_cmd():
    cmd = [
        "rpicam-vid",
        "-n",
        "--codec",
        "mjpeg",
        "--width",
        str(WIDTH),
        "--height",
        str(HEIGHT),
        "--framerate",
        str(settings["preview_fps"]),
        "--timeout",
        "0",
        "--output",
        "-",
    ]
    if settings["hflip"]:
        cmd.append("--hflip")
    if settings["vflip"]:
        cmd.append("--vflip")
    return cmd


def detect_audio_input():
    if not shutil.which("arecord"):
        return None
    proc = run(["arecord", "-L"], timeout=8)
    out = proc.stdout.decode("utf-8", "replace")
    out_lower = out.lower()
    if "seeed2micvoicec" in out_lower and "\ncapture\n" in f"\n{out_lower}\n":
        return "default"
    devices = []
    for line in run(["arecord", "-l"], timeout=8).stdout.decode("utf-8", "replace").splitlines():
        match = re.search(r"card (\d+): .*?\[(.*?)\], device (\d+):", line)
        if not match:
            continue
        card = int(match.group(1))
        card_name = match.group(2).lower()
        device = int(match.group(3))
        devices.append((card, device, card_name))
    if not devices:
        return None
    for card, device, card_name in devices:
        if any(tag in card_name for tag in ("wm8960", "seeed", "respeaker", "mic hat")):
            return f"plughw:{card},{device}"
    card, device, _ = devices[0]
    return f"plughw:{card},{device}"


AUDIO_DEVICE = detect_audio_input()
if AUDIO_DEVICE:
    AUDIO_STATUS = AUDIO_DEVICE


class RecordingSession:
    def __init__(self, path, mode, writer, thread, queue_obj, proc=None, fifo_path=None, audio_device=None):
        self.path = path
        self.mode = mode
        self.writer = writer
        self.thread = thread
        self.queue = queue_obj
        self.proc = proc
        self.fifo_path = fifo_path
        self.audio_device = audio_device
        self.active = True


def get_remap(width, height, strength):
    key = (width, height, strength)
    cached = remap_cache.get(key)
    if cached is not None:
        return cached
    if strength <= 0:
        remap_cache[key] = None
        return None

    # Positive strength pushes pixels outward in the output image, which
    # counteracts barrel/fisheye distortion from the lens.
    k = 0.35 * (strength / 100.0)
    xs = np.linspace(-1.0, 1.0, width, dtype=np.float32)
    ys = np.linspace(-1.0, 1.0, height, dtype=np.float32)
    xg, yg = np.meshgrid(xs, ys)
    r2 = xg * xg + yg * yg
    scale = 1.0 - k * r2
    src_x = ((xg * scale) + 1.0) * 0.5 * (width - 1)
    src_y = ((yg * scale) + 1.0) * 0.5 * (height - 1)
    map_x = np.clip(src_x, 0, width - 1)
    map_y = np.clip(src_y, 0, height - 1)
    remap_cache[key] = (map_x, map_y)
    return remap_cache[key]


def dewarp_frame(frame, strength):
    if strength <= 0:
        return frame
    img = Image.open(io.BytesIO(frame)).convert("RGB")
    arr = np.asarray(img)
    height, width = arr.shape[:2]
    remap = get_remap(width, height, strength)
    if remap is None:
        return frame
    map_x, map_y = remap

    x0 = np.floor(map_x).astype(np.int32)
    y0 = np.floor(map_y).astype(np.int32)
    x1 = np.clip(x0 + 1, 0, width - 1)
    y1 = np.clip(y0 + 1, 0, height - 1)
    wx = map_x - x0
    wy = map_y - y0

    top = arr[y0, x0] * (1.0 - wx)[..., None] + arr[y0, x1] * wx[..., None]
    bottom = arr[y1, x0] * (1.0 - wx)[..., None] + arr[y1, x1] * wx[..., None]
    out = top * (1.0 - wy)[..., None] + bottom * wy[..., None]
    out = np.clip(out, 0, 255).astype(np.uint8)
    result = Image.fromarray(out, mode="RGB")
    buf = io.BytesIO()
    result.save(buf, format="JPEG", quality=90, optimize=False)
    return buf.getvalue()


def camera_worker():
    global latest_frame, latest_frame_at, latest_error, settings_version
    current_version = -1
    while not stop_event.is_set():
        with state_cv:
            while not stop_event.is_set() and settings_version == current_version:
                state_cv.wait(timeout=1)
            if stop_event.is_set():
                break
            current_version = settings_version
            cmd = rpicam_cmd()

        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        buf = bytearray()
        try:
            while not stop_event.is_set():
                if current_version != settings_version:
                    break
                chunk = proc.stdout.read(8192)
                if not chunk:
                    break
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
                    frame = dewarp_frame(frame, settings["dewarp_strength"])
                    session = None
                    with state_cv:
                        latest_frame = frame
                        latest_frame_at = time.time()
                        latest_error = ""
                        session = record_session
                        state_cv.notify_all()
                    if session is not None and session.active:
                        try:
                            session.queue.put_nowait(frame)
                        except queue.Full:
                            with state_cv:
                                latest_error = "recording backlog: dropped frame"
                                state_cv.notify_all()
        finally:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except Exception:
                pass
            try:
                stderr = proc.stderr.read(4000)
            except Exception:
                stderr = b""
            with state_cv:
                if not stop_event.is_set() and current_version == settings_version:
                    msg = stderr.decode("utf-8", "replace").strip()
                    latest_error = msg[-2000:] if msg else "camera worker exited"
                    state_cv.notify_all()
        if not stop_event.is_set():
            time.sleep(0.5)


def safe_recording(name):
    if "/" in name or "\\" in name or name.startswith(".") or not name.endswith((".mjpeg", ".mkv")):
        return None
    path = RECORD_DIR / name
    try:
        path.resolve().relative_to(RECORD_DIR.resolve())
    except ValueError:
        return None
    return path if path.exists() else None


def recordings():
    files = list(RECORD_DIR.glob("*.mjpeg")) + list(RECORD_DIR.glob("*.mkv"))
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def recording_active():
    with state_lock:
        if record_session is None:
            return False, None
        return True, record_session.path


def start_recording():
    global record_session
    with state_lock:
        if record_session is not None:
            return False, str(record_session.path)

    stamp = time.strftime("recording-%Y%m%d-%H%M%S") + f"-{time.time_ns() % 1_000_000_000:09d}"
    audio_device = AUDIO_DEVICE
    use_mux = bool(FFMPEG and audio_device)

    if use_mux:
        path = RECORD_DIR / f"{stamp}.mkv"
        fifo_path = RECORD_DIR / f".{stamp}.mjpg.fifo"
        queue_obj = queue.Queue(maxsize=240)
        if fifo_path.exists():
            fifo_path.unlink()
        os.mkfifo(fifo_path)
        cmd = [
            FFMPEG,
            "-y",
            "-loglevel",
            "error",
            "-thread_queue_size",
            "512",
            "-f",
            "mjpeg",
            "-framerate",
            str(settings["preview_fps"]),
            "-i",
            str(fifo_path),
            "-thread_queue_size",
            "512",
            "-f",
            "alsa",
            "-i",
            audio_device,
            "-af",
            f"aresample=async=1:first_pts=0,volume={settings['audio_gain_db']}dB",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            str(path),
        ]
        proc = subprocess.Popen(cmd, start_new_session=True)

        def writer_loop():
            try:
                # Open the FIFO in the background so the HTTP start button
                # returns immediately instead of blocking on ffmpeg startup.
                with open(fifo_path, "wb", buffering=0) as writer:
                    session.writer = writer
                    while True:
                        frame = queue_obj.get()
                        if frame is None:
                            break
                        writer.write(frame)
            except Exception as exc:
                with state_cv:
                    global latest_error
                    latest_error = f"record writer failed: {exc}"
                    state_cv.notify_all()
            finally:
                try:
                    proc.wait(timeout=10)
                except Exception:
                    try:
                        proc.terminate()
                        proc.wait(timeout=5)
                    except Exception:
                        try:
                            proc.kill()
                        except Exception:
                            pass
                try:
                    if fifo_path.exists():
                        fifo_path.unlink()
                except Exception:
                    pass

        thread = threading.Thread(target=writer_loop, daemon=True)
        session = RecordingSession(path, "muxed", None, thread, queue_obj, proc=proc, fifo_path=fifo_path, audio_device=audio_device)
        thread.start()
        with state_lock:
            record_session = session
        return True, str(path)

    path = RECORD_DIR / f"{stamp}.mjpeg"
    queue_obj = queue.Queue(maxsize=240)
    writer = open(path, "ab", buffering=0)

    def writer_loop():
        try:
            while True:
                frame = queue_obj.get()
                if frame is None:
                    break
                writer.write(frame)
        except Exception as exc:
            with state_cv:
                global latest_error
                latest_error = f"record writer failed: {exc}"
                state_cv.notify_all()
        finally:
            try:
                writer.close()
            except Exception:
                pass

    thread = threading.Thread(target=writer_loop, daemon=True)
    session = RecordingSession(path, "video", writer, thread, queue_obj)
    thread.start()
    with state_lock:
        record_session = session
    return True, str(path)


def finalize_recording(session):
    try:
        session.queue.put_nowait(None)
    except Exception:
        pass
    session.thread.join(timeout=8)
    if session.thread.is_alive():
        try:
            session.queue.put_nowait(None)
        except Exception:
            pass
        session.thread.join(timeout=5)
    if session.proc is not None:
        try:
            session.proc.wait(timeout=2)
        except Exception:
            try:
                session.proc.terminate()
                session.proc.wait(timeout=5)
            except Exception:
                try:
                    session.proc.kill()
                except Exception:
                    pass


def stop_recording():
    global record_session
    with state_lock:
        if record_session is None:
            return False, "not recording"
        session = record_session
        record_session = None
        session.active = False
    threading.Thread(target=finalize_recording, args=(session,), daemon=True).start()
    return True, str(session.path)


def apply_settings(params):
    global settings_version
    changed = False
    with state_cv:
        if "hflip" in params:
            new_hflip = True
        else:
            new_hflip = False
        if settings["hflip"] != new_hflip:
            settings["hflip"] = new_hflip
            changed = True

        if "vflip" in params:
            new_vflip = True
        else:
            new_vflip = False
        if settings["vflip"] != new_vflip:
            settings["vflip"] = new_vflip
            changed = True

        try:
            strength = int(params.get("dewarp_strength", [str(settings["dewarp_strength"])])[0])
        except ValueError:
            strength = settings["dewarp_strength"]
        strength = max(0, min(100, strength))
        if settings["dewarp_strength"] != strength:
            settings["dewarp_strength"] = strength
            remap_cache.clear()
            changed = True

        try:
            fps = int(params.get("preview_fps", [str(settings["preview_fps"])])[0])
        except ValueError:
            fps = settings["preview_fps"]
        fps = max(1, min(30, fps))
        if settings["preview_fps"] != fps:
            settings["preview_fps"] = fps
            changed = True

        try:
            gain = int(params.get("audio_gain_db", [str(settings["audio_gain_db"])])[0])
        except ValueError:
            gain = settings["audio_gain_db"]
        gain = max(0, min(48, gain))
        if settings["audio_gain_db"] != gain:
            settings["audio_gain_db"] = gain
            changed = True

        if changed:
            settings_version += 1
            state_cv.notify_all()
    return changed


def snapshot_frame(timeout=5.0):
    deadline = time.time() + timeout
    with state_cv:
        seen = latest_frame_at
        while time.time() < deadline:
            if latest_frame is not None and latest_frame_at != seen:
                return latest_frame
            remaining = deadline - time.time()
            if remaining > 0:
                state_cv.wait(timeout=remaining)
        return latest_frame


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def redirect(self):
        self.send_response(303)
        self.send_header("Location", "/")
        self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        body = self.rfile.read(int(self.headers.get("Content-Length", "0") or 0)).decode("utf-8", "replace")
        params = parse_qs(body)
        action = parse_qs(parsed.query).get("action", [""])[0]
        if action == "start":
            start_recording()
        elif action == "stop":
            stop_recording()
        elif action == "apply":
            apply_settings(params)
        self.redirect()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/snapshot.jpg":
            frame = snapshot_frame()
            if frame is None:
                self.send_error(503, "No frame available")
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(frame)))
            self.end_headers()
            self.wfile.write(frame)
            return

        if parsed.path == "/stream.mjpg":
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            last_seen = 0.0
            while True:
                with state_cv:
                    while latest_frame_at == last_seen and not stop_event.is_set():
                        state_cv.wait(timeout=10)
                    if stop_event.is_set():
                        return
                    frame = latest_frame
                    last_seen = latest_frame_at
                if frame is None:
                    continue
                try:
                    self.wfile.write(b"--frame\r\n")
                    self.wfile.write(b"Content-Type: image/jpeg\r\n")
                    self.wfile.write(f"Content-Length: {len(frame)}\r\n\r\n".encode())
                    self.wfile.write(frame + b"\r\n")
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    return

        if parsed.path.startswith("/recordings/"):
            path = safe_recording(unquote(parsed.path.removeprefix("/recordings/")))
            if path is None:
                self.send_error(404, "Recording not found")
                return
            self.send_response(200)
            content_type = "video/x-motion-jpeg"
            if path.suffix == ".mkv":
                content_type = "video/x-matroska"
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Disposition", f"attachment; filename={quote(path.name)}")
            self.send_header("Content-Length", str(path.stat().st_size))
            self.end_headers()
            with path.open("rb") as f:
                while chunk := f.read(1024 * 1024):
                    self.wfile.write(chunk)
            return

        if parsed.path == "/health":
            p = run(["rpicam-hello", "--list-cameras"], timeout=15)
            out = p.stdout.decode("utf-8", "replace")
            ok = p.returncode == 0 and "ov5647" in out
            self.send_response(200 if ok else 503)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(("ok\n" if ok else "fail\n").encode())
            self.wfile.write(out.encode())
            return

        active, path = recording_active()
        rows = "".join(
            f'<li><a href="/recordings/{quote(p.name)}">{html.escape(p.name)}</a> '
            f'<span>{p.stat().st_size / 1048576:.1f} MiB</span></li>'
            for p in recordings()[:20]
        )
        status = "recording " + html.escape(str(path)) if active else "idle"
        color = "#ff7777" if active else "#8be28b"
        audio_status = html.escape(AUDIO_STATUS or "not detected")
        record_mode = "muxed audio+video" if (FFMPEG and AUDIO_DEVICE) else "video only"
        checked_h = "checked" if settings["hflip"] else ""
        checked_v = "checked" if settings["vflip"] else ""
        page = f"""<!doctype html>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Pi Camera</title>
<style>
body {{ max-width: 980px; margin: 24px auto; padding: 0 16px; font-family: sans-serif; background:#111; color:#eee; }}
.card {{ background:#1b1b1b; border:1px solid #333; border-radius:16px; padding:18px; }}
.grid {{ display:grid; grid-template-columns: 1fr 320px; gap:16px; }}
img {{ width:100%; border-radius:12px; background:#000; }}
button {{ padding:10px 14px; border:0; border-radius:10px; margin-right:8px; cursor:pointer; }}
.start {{ background:#20b26b; color:#04140b; }} .stop {{ background:#e85656; color:#210202; }} .apply {{ background:#ddd; color:#111; width:100%; }}
.status {{ color:{color}; font-weight:700; }}
.muted, li span {{ color:#aaa; }}
.control {{ display:block; margin: 10px 0; }}
.control input[type=range] {{ width:100%; }}
a {{ color:#9ed3ff; }}
@media (max-width: 900px) {{ .grid {{ grid-template-columns: 1fr; }} }}
</style>
<div class=card>
<h1>Pi Camera</h1>
<p>Status: <span class=status>{status}</span></p>
<p class=muted>Modern OV5647 stack. The preview stream is MJPEG at {settings["preview_fps"]} fps. Dewarp uses a radial remap model in Python, not a crop.</p>
<p class=muted>Mic input: {audio_status}. Recording mode: {record_mode}.</p>
<div class=grid>
<section>
<img id=preview src="/stream.mjpg" alt="camera stream">
<p>
<form method=post action="/?action=start" style="display:inline"><button class=start>Start recording</button></form>
<form method=post action="/?action=stop" style="display:inline"><button class=stop>Stop recording</button></form>
</p>
<h2>Recordings</h2>
<ul>{rows or "<li>No recordings yet</li>"}</ul>
</section>
<aside>
<h2>Controls</h2>
<form method=post action="/?action=apply">
<label class=control><input type=checkbox name=hflip {checked_h}> Invert horizontally</label>
<label class=control><input type=checkbox name=vflip {checked_v}> Invert vertically</label>
<label class=control>Dewarp model strength: <output>{settings["dewarp_strength"]}</output>
<input name=dewarp_strength type=range min=0 max=100 step=1 value={settings["dewarp_strength"]} oninput="this.previousElementSibling.value=this.value">
</label>
<label class=control>Preview FPS: <output>{settings["preview_fps"]}</output>
<input name=preview_fps type=range min=1 max=30 step=1 value={settings["preview_fps"]} oninput="this.previousElementSibling.value=this.value">
</label>
<label class=control>Audio gain: <output>{settings["audio_gain_db"]} dB</output>
<input name=audio_gain_db type=range min=0 max=48 step=1 value={settings["audio_gain_db"]} oninput="this.previousElementSibling.value=this.value + ' dB'">
</label>
<button class=apply>Apply</button>
</form>
</aside>
</div>
</div>
"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(page.encode())


if __name__ == "__main__":
    threading.Thread(target=camera_worker, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
