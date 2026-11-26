"""Follow a visible target using PC detections and local motion policy."""

import threading
import time

from perception.vision import DETECT_URL, box_center_x, detect_target, resolve_label
from skills.runtime import (
    SkillStatus,
    VisualTurnController,
    forward_bounds,
    timed_velocity,
    turn_bounds,
    turn_pulse_seconds,
)
from skills.tuning import (
    FORWARD_MAX,
    FORWARD_MIN,
    TURN_DEADBAND,
    TURN_KP,
    TURN_MAX,
    TURN_MIN,
    TURN_STOP_DEADBAND,
)

DEFAULT_HZ = 10
TARGET_HEIGHT = 0.68
STOP_HEIGHT = 0.82
LINEAR_KP = 50
MIN_LINEAR = FORWARD_MIN
MAX_LINEAR = FORWARD_MAX
STEER_KP = 60
STEER_DEADBAND = 0.03
MAX_STEER_TRIM = 9.0
PIVOT_DEADBAND = 0.22
FORWARD_DEADBAND = PIVOT_DEADBAND

_stop = threading.Event()
_state = SkillStatus({"running": False})


def _height(det):
    box = det.get("box") or [0, 0, 0, 0]
    return max(0.0, float(box[3]) - float(box[1]))


def _linear(box_height, offset, min_linear=MIN_LINEAR, max_linear=MAX_LINEAR):
    if box_height >= STOP_HEIGHT or abs(offset) > PIVOT_DEADBAND:
        return 0.0
    cmd = (TARGET_HEIGHT - box_height) * LINEAR_KP
    if cmd <= 0:
        return 0.0
    return min(max_linear, max(min_linear, cmd))


def _steer_trim(offset):
    if abs(offset) <= STEER_DEADBAND:
        return 0.0
    return max(-MAX_STEER_TRIM, min(MAX_STEER_TRIM, float(offset) * STEER_KP))


def follow(
    robot,
    target="person",
    hz=DEFAULT_HZ,
    cycles=0,
    detect_timeout=0.45,
):
    _stop.clear()
    target = str(target or "person").strip() or "person"
    period = 1 / max(1, float(hz))
    try:
        label, resolve_meta = resolve_label(target)
    except Exception as e:
        label, resolve_meta = target, {"resolve_error": str(e)}

    _state.reset(
        running=True,
        skill="follow",
        phase="track",
        target=target,
        label=label,
        detector=DETECT_URL,
        target_height=TARGET_HEIGHT,
        stop_height=STOP_HEIGHT,
        **resolve_meta,
    )
    loop, cx = 0, 0.5
    steering = VisualTurnController(TURN_STOP_DEADBAND, alpha=0.72)
    try:
        with robot.vision.exclusive():
            while not _stop.is_set() and (not cycles or loop < cycles):
                loop += 1
                started = time.monotonic()
                try:
                    det, meta = detect_target(robot, label, cx, detect_timeout)
                except Exception as e:
                    det, meta = None, {"error": str(e)}
                meta = {"error": "", **(meta or {})}

                if _stop.is_set():
                    break
                # The stream request waits for a new frame. Bound the entire
                # request, including capture and time spent waiting for inference.
                if time.monotonic() - started > detect_timeout:
                    det = None
                    meta["error"] = "detection deadline exceeded"
                if not det:
                    steering = VisualTurnController(TURN_STOP_DEADBAND, alpha=0.72)
                    robot.movement.stop(source="follow")
                    _state.update(
                        phase="search",
                        veto="",
                        cycle=loop,
                        seen=False,
                        box=None,
                        linear=0,
                        turn=0,
                        **meta,
                    )
                    _stop.wait(max(0, period - (time.monotonic() - started)))
                    continue

                cx = box_center_x(det["box"])
                raw_offset = cx - 0.5
                offset, turn_allowed = steering.update(raw_offset)
                box_height = _height(det)
                min_turn, max_turn = turn_bounds(robot, TURN_MIN, TURN_MAX)
                min_fwd, max_fwd = forward_bounds(robot, MIN_LINEAR, MAX_LINEAR)
                base_linear = _linear(box_height, raw_offset, min_fwd, max_fwd)
                need_pivot = abs(raw_offset) > PIVOT_DEADBAND or (
                    base_linear == 0.0 and abs(raw_offset) > TURN_DEADBAND
                )
                if need_pivot:
                    linear = 0.0
                    turn = (
                        robot.movement.turn(
                            offset,
                            TURN_KP,
                            TURN_DEADBAND,
                            TURN_STOP_DEADBAND,
                            min_turn,
                            max_turn,
                        )
                        if turn_allowed
                        else 0.0
                    )
                    if turn and abs(turn) < min_turn:
                        turn = min_turn if turn > 0 else -min_turn
                    if turn:
                        result = timed_velocity(
                            robot,
                            _stop,
                            0.0,
                            turn,
                            turn_pulse_seconds(raw_offset),
                            "follow",
                            settle_seconds=0.05,
                        )
                    else:
                        robot.movement.stop(source="follow")
                        result = None
                elif base_linear > 0.0:
                    # Keep both wheels >= min_fwd while smoothly steering toward center.
                    trim = _steer_trim(raw_offset)
                    max_trim = max(0.0, min(MAX_STEER_TRIM, max_fwd - min_fwd))
                    turn = max(-max_trim, min(max_trim, trim))
                    linear = min(max_fwd, max(base_linear, min_fwd + abs(turn)))
                    result = robot.movement.set_velocity(linear, turn, source="follow")
                else:
                    linear = turn = 0.0
                    robot.movement.stop(source="follow")
                    result = None
                veto = (result or {}).get("veto") or ""
                if veto:
                    linear = turn = 0.0
                _state.update(
                    phase="blocked" if veto else "follow" if linear else "turn" if turn else "hold",
                    veto=veto,
                    cycle=loop,
                    seen=True,
                    box=det["box"],
                    score=det.get("score"),
                    cx=round(cx, 3),
                    raw_offset=round(raw_offset, 3),
                    offset=round(offset, 3),
                    height=round(box_height, 3),
                    linear=round(linear, 1),
                    turn=round(turn, 1),
                    turn_reversal_held=not turn_allowed,
                    **meta,
                )
                _stop.wait(max(0, period - (time.monotonic() - started)))
    finally:
        robot.movement.stop(source="follow")
        _state.update(running=False)


def stop_follow():
    _stop.set()
    return status()


def is_running():
    return bool(_state.snapshot().get("running"))


def status():
    return _state.snapshot()
