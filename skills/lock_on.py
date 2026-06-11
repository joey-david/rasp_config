"""Delay-aware person lock-on driven by remote person detections."""
import time
import threading

_stop = threading.Event()
_status = {"running": False}


def _clamp(x, lo, hi):
    return max(lo, min(hi, float(x)))

def _person(d):
    return str(d.get("label", "")).lower() in {"person", "human", "people"}

def _center(box):
    return (float(box[0]) + float(box[2])) * 0.5

def _best_detection(robot, last_cx):
    best, best_score = None, -1
    for d in getattr(robot.perception, "detections", []) or []:
        box = d.get("box") or []
        if not _person(d) or len(box) != 4:
            continue
        cx = _center(box)
        score = float(d.get("score") or 0.5) - 0.4 * abs(cx - last_cx)
        if score > best_score:
            best, best_score = d, score
    return best

def _turn(err, vel, kp, kd, deadband, limit):
    cmd = kp * err + kd * vel
    if abs(err) < deadband and abs(vel) < 0.05:
        return 0.0
    if abs(cmd) < 10:
        cmd = 10 if cmd > 0 else -10
    return _clamp(cmd, -limit, limit)

def lock_on(robot, target="person", track_id=None, hz=30, kp=115, kd=36,
            lead=0.10, deadband=0.025, max_turn=55, max_age=0.45, cycles=0):
    global _status
    _stop.clear()
    period = 1 / max(1, float(hz))
    cx = 0.5
    vel = 0.0
    last_t = None
    last_packet = 0.0
    last_seen = 0.0
    loop = 0
    _status = {"running": True, "target": target, "seen": False}
    try:
        while not _stop.is_set() and (not cycles or loop < cycles):
            loop += 1
            now = time.time()
            det = None
            packet_t = float(getattr(robot.perception.receiver, "received_at", 0) or 0)
            if packet_t > last_packet:
                det = _best_detection(robot, cx)
                last_packet = packet_t
            if det:
                z = _center(det["box"])
                t = float(det.get("captured_at") or packet_t or now)
                if last_t is not None and t > last_t:
                    measured_v = _clamp((z - cx) / max(0.02, t - last_t), -2.0, 2.0)
                    vel = 0.55 * vel + 0.45 * measured_v
                cx, last_t, last_seen = z, t, now
            age = now - last_seen if last_seen else 999
            if age > max_age:
                robot.set_velocity(0, 0, source="lock-on")
                _status = {"running": True, "target": target, "seen": False, "age": round(age, 3), "turn": 0}
            else:
                latency = max(0.0, now - (last_t or now))
                predicted = _clamp(cx + vel * min(0.35, latency + lead), 0, 1)
                err = predicted - 0.5
                turn = _turn(err, vel, kp, kd, deadband, max_turn)
                robot.set_velocity(0, turn, source="lock-on")
                _status = {"running": True, "target": target, "seen": True,
                           "box": det.get("box") if det else _status.get("box"),
                           "cx": round(cx, 3), "predicted": round(predicted, 3),
                           "offset": round(err, 3), "vel": round(vel, 3),
                           "latency": round(latency, 3), "age": round(age, 3),
                           "turn": round(turn, 1)}
            time.sleep(period)
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
