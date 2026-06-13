"""Lock-on variant that uses visual odometry to overcome static turn friction."""

import math
import threading
import time

from perception.vision import DETECT_URL, box_center_x, detect_target, resolve_label

_stop = threading.Event()
_status = {"running": False}


def _sign(x):
    return 1 if x > 0 else -1 if x < 0 else 0


def _rotation_seen(odom, turn, min_rad_s):
    if not odom.get("fresh") or not turn:
        return False
    measured = float(odom.get("rad_s") or 0.0)
    return _sign(measured) == _sign(turn) and abs(measured) >= min_rad_s


def lock_on_odometric(
    robot,
    target="person",
    track_id=None,
    hz=12,
    kp=95,
    deadband=0.025,
    stop_deadband=0.010,
    min_turn=18,
    max_turn=52,
    detect_timeout=0.45,
    min_rad_s=0.08,
    boost_step=3,
    boost_decay=5,
    max_boost=24,
    search_turn=28,
    cycles=0,
):
    global _status
    _stop.clear()
    robot.odometry.reset()
    period = 1 / max(1, float(hz))
    cx, loop = 0.5, 0
    boost, last_sign = 0.0, 0
    try:
        target_label, resolve_meta = resolve_label(target)
    except Exception as e:
        target_label, resolve_meta = target, {"resolve_error": str(e)}

    _status = {
        "running": True,
        "target": target,
        "label": target_label,
        "seen": False,
        "detector": DETECT_URL,
        "mode": "odometric",
        **resolve_meta,
    }

    try:
        while not _stop.is_set() and (not cycles or loop < cycles):
            loop += 1
            started = time.time()
            odom = robot.odometry.update()
            try:
                det, meta = detect_target(robot, target_label, cx, detect_timeout)
            except Exception as e:
                det, meta = None, {"error": str(e)}

            if det:
                cx = box_center_x(det["box"])
                err = cx - 0.5
                turn = robot.movement.turn(
                    err, kp, deadband, stop_deadband, min_turn, max_turn
                )
            else:
                err = None
                turn = float(search_turn)

            turn_sign = _sign(turn)
            if turn_sign != last_sign:
                boost = 0.0
                last_sign = turn_sign

            moving = _rotation_seen(odom, turn, min_rad_s)
            if turn:
                boost = (
                    max(0.0, boost - boost_decay)
                    if moving
                    else min(max_boost, boost + boost_step)
                )
            else:
                boost = 0.0

            cmd = turn + turn_sign * boost
            cmd = robot.movement.clamp(cmd, -max_turn, max_turn)
            target_rad_s = math.copysign(min_rad_s, cmd) if cmd else 0.0
            robot.movement.set_rotation_target(target_rad_s)
            robot.movement.set_velocity(0, cmd, source="lock-on-odometric")

            _status = {
                "running": True,
                "target": target,
                "label": target_label,
                "seen": bool(det),
                "box": det.get("box") if det else None,
                "score": det.get("score") if det else None,
                "cx": round(cx, 3) if det else None,
                "offset": round(err, 3) if err is not None else None,
                "turn": round(cmd, 1),
                "base_turn": round(turn, 1),
                "boost": round(boost, 1),
                "rotation_seen": moving,
                "odom_rad_s": round(float(odom.get("rad_s") or 0.0), 3),
                "odom_score": round(float(odom.get("score") or 0.0), 3),
                "mode": "odometric",
                **resolve_meta,
                **meta,
            }

            time.sleep(max(0, period - (time.time() - started)))
    finally:
        robot.movement.stop(source="lock-on-odometric")
        robot.movement.set_rotation_target(0.0)
        _status = {**_status, "running": False}


def stop_lock():
    _stop.set()
    return status()


def is_running():
    return bool(_status.get("running"))


def status():
    return dict(_status)
