#!/usr/bin/env python3
"""Thin web cockpit. No GPIO, no motor mapping, no movement math."""
import json
import mimetypes
from pathlib import Path
import signal
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from robot_api import robot
from skills import emotes
from skills.find import stop_find, status as find_status
from skills.follow import follow, stop_follow, status as follow_status, is_running as follow_running
from hardware.motion_udp import UDPMotionServer
from skills.lock_on import lock_on, stop_lock, status as lock_status, is_running as lock_running
from skills.procedures import (
    is_running as procedure_running,
    list_procedures,
    run_procedure,
    status as procedure_status,
    stop_procedure,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"
_skill_claim = None
_skill_claim_lock = threading.Lock()


class RobotServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64


def _runtime_skill_active():
    level2 = robot.skills.status()["layer2"]
    gauge = getattr(robot, "power_gauge", None)
    return bool(
        lock_running()
        or find_status().get("running")
        or follow_running()
        or procedure_running()
        or (gauge and gauge.status().get("running"))
        or level2.get("running")
        or robot.autonomy.status().get("running")
    )


def active_skill():
    with _skill_claim_lock:
        return bool(_skill_claim or _runtime_skill_active())


robot.skill_active = active_skill


def claimed_skill():
    with _skill_claim_lock:
        return _skill_claim


def _claim_skill(name):
    global _skill_claim
    with _skill_claim_lock:
        if _skill_claim or _runtime_skill_active():
            return False
        _skill_claim = name
        return True


def _release_skill(name):
    global _skill_claim
    with _skill_claim_lock:
        if _skill_claim == name:
            _skill_claim = None


def _call_skill(name, call):
    if not _claim_skill(name):
        return 409, {"ok": False, "error": "another skill is already running"}
    try:
        return 200, call()
    except Exception as exc:
        print(f"[web] {name} failed: {exc}", flush=True)
        return 500, {"ok": False, "error": str(exc)}
    finally:
        _release_skill(name)


def _start_skill(name, call, response):
    if not _claim_skill(name):
        return 409, {"ok": False, "error": "another skill is already running"}

    def run():
        try:
            call()
        except Exception as exc:
            print(f"[web] {name} failed: {exc}", flush=True)
        finally:
            _release_skill(name)

    threading.Thread(target=run, daemon=True, name=name).start()
    return 200, response


def stop_all_skills():
    robot.autonomy.stop()
    robot.skills.stop()
    gauge = getattr(robot, "power_gauge", None)
    if gauge:
        gauge.stop()
    stop_find()
    stop_follow()
    stop_lock()
    stop_procedure()
    emotes.stop_emote()


def handle_skill_post(path, body):
    if path == "/skill/stop":
        stop_all_skills()
        return 200, {"ok": True, "stopped": True}
    if path in {"/skill/goto", "/skill/go-to"}:
        return _call_skill("go-to", lambda: robot.goto(body.get("target", "")))
    if path == "/skill/find":
        return _call_skill(
            "find",
            lambda: robot.find(
                body.get("target", ""),
                body.get("search_speed", body.get("search-speed", 35)),
                body.get("max_cycles", 15),
            ),
        )
    if path == "/skill/follow":
        target = str(body.get("target") or "person").strip() or "person"
        return _start_skill(
            "follow",
            lambda: follow(
                robot=robot,
                target=target,
                cycles=int(body.get("cycles") or 0),
            ),
            {"ok": True, "skill": "follow", "target": target},
        )
    if path == "/skill/push":
        return _call_skill("push", lambda: robot.push(body.get("target", "")))
    if path == "/skill/push-to":
        return _call_skill(
            "push-to",
            lambda: robot.push_to(
                body.get("source", body.get("target", "")),
                body.get("destination", ""),
            ),
        )
    if path == "/skill/emote":
        return _call_skill(
            "emote",
            lambda: robot.emote(body.get("name", ""), body.get("scale", 1.0)),
        )
    if path in {"/skill/power-gauge", "/skill/calibrate-power"}:
        kwargs = {
            k: body[k]
            for k in (
                "start_power",
                "step",
                "max_power",
                "pulse_seconds",
                "settle_seconds",
                "margin",
                "confirm_reverse",
            )
            if k in body
        }
        return _call_skill("power-gauge", lambda: robot.calibrate_power(**kwargs))
    if path == "/skill/procedure":
        proc_id = str(body.get("id") or "").strip()
        target = str(body.get("target") or "person").strip() or "person"
        valid = {p["id"] for p in list_procedures()}
        if proc_id not in valid:
            return 400, {"ok": False, "error": f"unknown procedure: {proc_id!r}"}
        return _start_skill(
            "procedure",
            lambda: run_procedure(robot, proc_id, target=target),
            {"ok": True, "skill": "procedure", "id": proc_id, "target": target},
        )
    if path != "/skill/lock-on":
        return None
    target = str(body.get("target") or "person").strip() or "person"
    return _start_skill(
        "lock-on",
        lambda: lock_on(
            robot=robot,
            target=target,
            track_id=body.get("track_id"),
            cycles=int(body.get("cycles") or 0),
        ),
        {"ok": True, "skill": "lock-on", "target": target},
    )


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
        if p == "/drive":
            if b.get("keys") and active_skill():
                stop_all_skills()
                return self.send(409, {"ok": False, "error": "skill stopping; retry movement"})
            return self.send(200, robot.drive_keys(b.get("keys", ""), b.get("power"), b.get("seq")))
        if p == "/motion/set_velocity":
            if active_skill():
                return self.send(409, {"ok": False, "error": "another skill is already running"})
            return self.send(200, robot.set_velocity(b.get("linear", 0), b.get("angular", 0), b.get("seq"), "http"))
        if p == "/motion/stop": return self.send(200, robot.stop(b.get("seq"), "http"))
        if p == "/odometry/rotation": return self.send(200, robot.odometry.set_rotation_target(b.get("rad_s", 0)))
        if p == "/camera/settings":
            robot.apply_camera_settings(**b)
            return self.send(200, robot.status())
        if p == "/autonomy/start":
            code, payload = _call_skill(
                "autonomy-start",
                lambda: robot.autonomy.start(b.get("goal"), b.get("max_steps", 12)),
            )
            return self.send(code, payload)
        if p == "/autonomy/stop": return self.send(200, robot.autonomy.stop())
        skill_response = handle_skill_post(p, b)
        if skill_response:
            code, body = skill_response
            return self.send(code, body)
        self.send_error(404)

    def do_GET(self):
        p = urlparse(self.path).path
        if p == "/": return self.send_static("index.html", "text/html; charset=utf-8")
        if p.startswith("/static/"): return self.send_static(p.removeprefix("/static/"))
        if p == "/api/emotes": return self.send(200, {"emotes": emotes.names()})
        if p == "/api/procedures": return self.send(200, {"procedures": list_procedures(), "status": procedure_status()})
        if p == "/api/state":
            status = robot.status()
            status["skill_runner"] = {
                "claimed": claimed_skill(),
                "find": find_status(),
                "follow": follow_status(),
                "lock_on": lock_status(),
                "procedure": procedure_status(),
            }
            return self.send(200, status)
        if p == "/api/detections": return self.send(200, robot.perception.status())
        if p == "/api/autonomy": return self.send(200, robot.autonomy.status())
        if p == "/api/odometry": return self.send(200, robot.odometry.update())
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
