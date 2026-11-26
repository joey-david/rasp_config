"""Pi-side lock-on: ask the PC to detect target, then compute motion locally."""

import threading
import time

from perception.vision import DETECT_URL, box_center_x, detect_target, resolve_label
from skills.runtime import VisualTurnController, timed_velocity
from skills.tuning import (
    TURN_DEADBAND,
    TURN_KP,
    TURN_MAX,
    TURN_MIN,
    TURN_STOP_DEADBAND,
)

_stop = threading.Event()
_status = {"running": False}
CONTROL_PULSE_SECONDS = 0.08


def lock_on(
    robot,
    target="person",
    track_id=None,
    hz=12,
    kp=TURN_KP,
    deadband=TURN_DEADBAND,
    stop_deadband=TURN_STOP_DEADBAND,
    min_turn=TURN_MIN,
    max_turn=TURN_MAX,
    detect_timeout=0.45,
    cycles=0,
):
    global _status
    _stop.clear()
    period = 1 / max(1, float(hz))
    cx, loop = 0.5, 0
    steering = VisualTurnController(stop_deadband)
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
        **resolve_meta,
    }
    try:
        with robot.vision.exclusive():
            while not _stop.is_set() and (not cycles or loop < cycles):
                loop += 1
                started = time.time()
                try:
                    det, meta = detect_target(robot, target_label, cx, detect_timeout)
                except Exception as e:
                    det, meta = None, {"error": str(e)}
                if not det:
                    robot.movement.set_velocity(0, 0, source="lock-on")
                    _status = {
                        "running": True,
                        "target": target,
                        "label": target_label,
                        "seen": False,
                        "turn": 0,
                        **resolve_meta,
                        **meta,
                    }
                    time.sleep(max(0, period - (time.time() - started)))
                    continue
                z = box_center_x(det["box"])
                raw_err = z - 0.5
                cx = z
                err, turn_allowed = steering.update(raw_err)
                turn = (
                    robot.movement.turn(
                        err, kp, deadband, stop_deadband, min_turn, max_turn
                    )
                    if turn_allowed
                    else 0.0
                )
                timed_velocity(
                    robot,
                    _stop,
                    0,
                    turn,
                    CONTROL_PULSE_SECONDS,
                    "lock-on",
                )
                _status = {
                    "running": True,
                    "target": target,
                    "label": target_label,
                    "seen": True,
                    "box": det["box"],
                    "score": det.get("score"),
                    "cx": round(cx, 3),
                    "raw_offset": round(raw_err, 3),
                    "offset": round(err, 3),
                    "turn": round(turn, 1),
                    "turn_reversal_held": not turn_allowed,
                    "stop_deadband": stop_deadband,
                    "min_turn": min_turn,
                    **resolve_meta,
                    **meta,
                }
                time.sleep(max(0, period - (time.time() - started)))
    finally:
        robot.movement.stop(source="lock-on")
        _status = {**_status, "running": False}


def stop_lock():
    _stop.set()
    return status()


def is_running():
    return bool(_status.get("running"))


def status():
    return dict(_status)
