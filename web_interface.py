#!/usr/bin/env python3
"""Thin web cockpit. No GPIO, no motor mapping, no movement math."""
import json
import mimetypes
from pathlib import Path
import signal
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from robot_api import robot, turbo
from motion_udp import UDPMotionServer
from skills.lock_on import lock_on, stop_lock, status as lock_status, is_running as lock_running
import threading

STATIC_DIR = Path(__file__).resolve().parent / "web" / "static"


class RobotServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass

    def body(self):
        n = int(self.headers.get("Content-Length", "0") or 0)
        try: return json.loads(self.rfile.read(n).decode() or "{}")
        except Exception: return {}

    def send(self, code, body, ctype="application/json; charset=utf-8", headers=None):
        if isinstance(body, (dict, list)): body = json.dumps(body).encode()
        elif isinstance(body, str): body = body.encode()
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items(): self.send_header(k, str(v))
        self.end_headers(); self.wfile.write(body)

    def send_static(self, name, ctype=None):
        path = (STATIC_DIR / name).resolve()
        if STATIC_DIR not in path.parents and path != STATIC_DIR:
            return self.send_error(404)
        if not path.is_file():
            return self.send_error(404)
        return self.send(200, path.read_bytes(), ctype or mimetypes.guess_type(path.name)[0] or "application/octet-stream")

    def do_POST(self):
        p, b = urlparse(self.path).path, self.body()
        if p == "/drive": return self.send(200, robot.drive_keys(b.get("keys", ""), b.get("power"), b.get("seq")))
        if p == "/motion/set_velocity": return self.send(200, robot.set_velocity(b.get("linear", 0), b.get("angular", 0), b.get("seq"), "http"))
        if p == "/motion/stop": return self.send(200, robot.stop(b.get("seq"), "http"))
        if p == "/camera/settings": robot.camera.apply_settings(**b); return self.send(200, robot.status())
        if p == "/skill/goto": return self.send(200, robot.goto(b.get("target", "")))
        if p == "/skill/push": return self.send(200, robot.push(b.get("target", "")))
        if p in ("/skill/lock-on", "/skill/lock-person"):
            if lock_running():
                return self.send(409, {"ok": False, "error": "lock-on already running", "status": lock_status()})
            target = b.get("target") or "person"
            t = threading.Thread(
                target=lock_on, daemon=True,
                kwargs={"robot": robot, "target": target,
                        "track_id": b.get("track_id"),
                        "cycles": int(b.get("cycles") or 0)})
            t.start()
            return self.send(200, {"ok": True, "skill": "lock-on", "target": target})
        if p == "/skill/stop":
            stop_lock()
            return self.send(200, {"ok": True, "stopped": True})
        if p == "/turbo":
            return self.send(200, turbo(b.get("on", True)))
        self.send_error(404)

    def do_GET(self):
        p = urlparse(self.path).path
        if p == "/": return self.send_static("index.html", "text/html; charset=utf-8")
        if p.startswith("/static/"): return self.send_static(p.removeprefix("/static/"))
        if p == "/api/state":
            status = robot.status()
            status["skill_runner"] = {"lock_on": lock_status()}
            return self.send(200, status)
        if p == "/api/detections": return self.send(200, robot.perception.status())
        if p == "/frame/latest.jpg":
            frame, frame_at, frame_id = robot.camera.latest()
            headers = {"X-Captured-At": frame_at, "X-Frame-Id": frame_id}
            return self.send(200, frame, "image/jpeg", headers) if frame else self.send_error(503, "No frame")
        if p == "/snapshot.jpg":
            frame = robot.snapshot()
            headers = {"X-Captured-At": robot.camera.frame_at, "X-Frame-Id": robot.camera.frame_id}
            return self.send(200, frame, "image/jpeg", headers) if frame else self.send_error(503, "No frame")
        if p == "/stream.mjpg": return self.stream()
        if p == "/health":
            r = subprocess.run(["rpicam-hello", "--list-cameras"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=15)
            return self.send(200 if r.returncode == 0 else 503, (("ok\n" if r.returncode == 0 else "fail\n") + r.stdout.decode()), "text/plain; charset=utf-8")
        self.send_error(404)

    def stream(self):
        self.send_response(200); self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame"); self.send_header("Cache-Control", "no-store"); self.end_headers()
        for frame in robot.camera.frames():
            try:
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n" + f"Content-Length: {len(frame)}\r\n\r\n".encode() + frame + b"\r\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError): return


def shutdown(*_):
    robot.close(); raise SystemExit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, shutdown); signal.signal(signal.SIGTERM, shutdown)
    robot.start()
    udp_motion = UDPMotionServer(robot).start()
    try: RobotServer(("0.0.0.0", 8080), Handler).serve_forever()
    finally:
        udp_motion.stop()
        robot.close()
