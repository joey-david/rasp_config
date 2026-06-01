"""Keep a visible object centered by turning in place."""
import threading
import time

from mischief_common.object_geometry import center


_stop = threading.Event()
_status = {"running": False, "target": None}


def _clamp(v, lo, hi):
    return max(lo, min(hi, float(v)))


def lock_on(robot, target="person", track_id=None, hz=30.0, kp=180.0, kd=65.0, deadband=0.04, max_turn=100.0, max_track_age=0.18, cycles=0):
    global _status
    _stop.clear()
    target = str(target or "person")
    period = 1 / max(1.0, float(hz))
    if track_id is None:
        obj = robot.perception.best(target)
        track_id = obj.get("track_id") if obj else None
    _status = {"running": True, "target": target, "track_id": track_id, "error": "", "seen": False}
    i = 0
    loop_times = []
    try:
        while not _stop.is_set() and (not cycles or i < cycles):
            started = time.time()
            i += 1
            obj = robot.perception.track(track_id) if track_id is not None else None
            if not obj:
                robot.set_velocity(0, 0, source="lock-on")
                _status = {**_status, "seen": False, "angular": 0, "error": "track not visible"}
                time.sleep(period)
                continue
            track_age = time.time() - float(obj.get("tracked_at") or 0)
            if track_age > max_track_age:
                robot.set_velocity(0, 0, source="lock-on")
                _status = {
                    "running": True, "target": target, "seen": False,
                    "label": obj.get("label"), "quality": obj.get("quality"),
                    "track_age": round(track_age, 3), "angular": 0,
                    "error": "track stale",
                }
                time.sleep(period)
                continue
            cx, _ = obj.get("center") or center(obj["box"])
            err = cx - 0.5
            quality = float(obj.get("quality") or 0)
            limit = max(12.0, max_turn * max(0.25, min(1.0, quality)))
            du = float((obj.get("velocity") or {}).get("du") or 0.0)
            angular = 0 if abs(err) < deadband else _clamp(kp * err + kd * du, -limit, limit)
            robot.set_velocity(0, angular, source="lock-on")
            loop_times = [t for t in loop_times if started - t <= 2.0] + [started]
            _status = {
                "running": True, "target": target, "seen": True,
                "track_id": track_id,
                "label": obj.get("label"), "quality": obj.get("quality"),
                "cx": round(cx, 3), "offset": round(err, 3), "angular": round(angular, 1),
                "du": round(du, 4), "track_age": round(track_age, 3), "loop_hz": round(len(loop_times) / 2.0, 1),
                "error": "",
            }
            time.sleep(max(0, period - (time.time() - started)))
    finally:
        robot.stop(source="lock-on")
        _status = {**_status, "running": False}


def stop_lock():
    _stop.set()
    return status()


def is_running():
    return bool(_status.get("running"))


def status():
    return dict(_status)
