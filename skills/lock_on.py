"""Pi-side lock-on: ask the PC to detect target, then compute motion locally."""

import threading
import time

from perception.vision import DETECT_URL, box_center_x, detect_target, resolve_label
from skills.runtime import (
    centering_turn,
    VisualTurnController,
    timed_velocity,
    turn_bounds,
    turn_pulse_seconds,
)
from skills.tuning import (
    TURN_DEADBAND,
    TURN_MAX,
    TURN_MIN,
    TURN_STOP_DEADBAND,
)

_stop = threading.Event()
_status = {"running": False}


def lock_on(
    robot,
    target="person",
    track_id=None,
    hz=12,
    kp=0.0,
    deadband=TURN_DEADBAND,
    stop_deadband=TURN_STOP_DEADBAND,
    min_turn=None,
    max_turn=None,
    detect_timeout=0.45,
    cycles=0,
):
    global _status
    _stop.clear()
    period = 1 / max(1, float(hz))
    cx, loop = 0.5, 0
    steering = VisualTurnController(stop_deadband, alpha=0.72)
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
                    steering = VisualTurnController(stop_deadband, alpha=0.72)
                    robot.movement.stop(source="lock-on")
                    _status = {
                        "running": True,
                        "target": target,
                        "label": target_label,
                        "seen": False,
                        "box": None,
                        "turn": 0,
                        **resolve_meta,
                        **meta,
                    }
                    _stop.wait(max(0, period - (time.time() - started)))
                    continue
                z = box_center_x(det["box"])
                raw_err = z - 0.5
                cx = z
                cur_min, cur_max = turn_bounds(robot, TURN_MIN, TURN_MAX)
                lo_turn = cur_min if min_turn is None else min_turn
                hi_turn = cur_max if max_turn is None else max_turn
                err, turn_allowed = steering.update(raw_err)
                turn = 0.0
                if turn_allowed and abs(raw_err) > deadband:
                    turn = centering_turn(err, lo_turn, hi_turn, stop_deadband, kp)
                if turn:
                    timed_velocity(
                        robot,
                        _stop,
                        0,
                        turn,
                        turn_pulse_seconds(raw_err),
                        "lock-on",
                        settle_seconds=0.05,
                    )
                else:
                    robot.movement.stop(source="lock-on")
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
                    "min_turn": lo_turn,
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
