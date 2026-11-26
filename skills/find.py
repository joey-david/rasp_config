"""Stop-and-look visual search backed by the PC YOLO detector."""

import threading

from perception.vision import (
    DETECT_URL,
    box_center_x,
    detect_target,
    resolve_label,
)
from skills.runtime import (
    SkillStatus,
    integer,
    number,
    timed_velocity,
    turn_bounds,
    turn_pulse_seconds,
)
from skills.tuning import (
    TURN_DEADBAND,
    TURN_KP,
    TURN_MAX,
    TURN_MIN,
    TURN_STOP_DEADBAND,
)

TURN_SECONDS = 0.3
SETTLE_SECONDS = 0.12
DEFAULT_SEARCH_SPEED = 35
DEFAULT_MAX_CYCLES = 15

CENTER_CYCLES = 8
CENTER_DEADBAND = TURN_DEADBAND

_stop = threading.Event()
_state = SkillStatus({"running": False})


class DetectionUnavailable(Exception):
    pass


def _target_label(target):
    try:
        label, meta = resolve_label(target)
    except Exception as e:
        label, meta = target, {"resolve_error": str(e)}
    return label, meta


def _find_once(robot, label, last_cx, timeout, cycle):
    try:
        det, meta = detect_target(robot, label, last_cx, timeout)
    except Exception as exc:
        det, meta = None, {"error": str(exc)}
    meta = {"error": "", **(meta or {})}
    if meta["error"] and not _stop.is_set():
        _state.update(phase="unavailable", seen=False, box=None, offset=None, **meta)
        raise DetectionUnavailable(meta["error"])
    if not det:
        _state.update(
            phase="detect",
            cycle=cycle,
            seen=False,
            box=None,
            offset=None,
            **meta,
        )
        return None, last_cx
    cx = box_center_x(det["box"])
    _state.update(
        phase="detect",
        cycle=cycle,
        seen=True,
        box=det["box"],
        score=det.get("score"),
        cx=round(cx, 3),
        offset=round(cx - 0.5, 4),
        **meta,
    )
    return det, cx


def _center(robot, target, label, det, cx, timeout):
    # Recheck the stream after each turn.
    best = det
    for cycle in range(1, CENTER_CYCLES + 1):
        if _stop.is_set():
            break
        err = cx - 0.5
        if abs(err) <= CENTER_DEADBAND:
            _state.update(
                phase="center",
                target=target,
                label=label,
                center_cycle=cycle,
                offset=round(err, 4),
                turn=0,
                centered=True,
            )
            return best, True
        min_turn, max_turn = turn_bounds(robot, TURN_MIN, TURN_MAX)
        turn = robot.movement.turn(
            err,
            TURN_KP,
            CENTER_DEADBAND,
            TURN_STOP_DEADBAND,
            min_turn,
            max_turn,
        )
        _state.update(
            phase="center",
            target=target,
            label=label,
            center_cycle=cycle,
            offset=round(err, 4),
            turn=round(turn, 1),
            centered=turn == 0,
        )
        if turn == 0:
            return best, True
        pulse = turn_pulse_seconds(err)
        print(
            f"[find] center {cycle}/{CENTER_CYCLES}: offset={err:.3f} "
            f"turn={turn:.1f} duration={pulse:.2f}s",
            flush=True,
        )
        timed_velocity(
            robot,
            _stop,
            0,
            turn,
            pulse,
            "find:center",
            settle_seconds=SETTLE_SECONDS,
        )
        if _stop.is_set():
            return None, False
        best, cx = _find_once(robot, label, cx, timeout, f"center-{cycle}")
        if not best:
            best, cx = _find_once(robot, label, cx, timeout, f"center-retry-{cycle}")
            if not best:
                return None, False
    err = cx - 0.5
    return best, bool(best and abs(err) <= CENTER_DEADBAND)


def _found_response(target, label, det, centered, cycles):
    _state.update(phase="found" if det else "lost", running=False, centered=centered)
    return {
        "ok": bool(det),
        "skill": "find",
        "target": target,
        "label": label,
        "found": bool(det),
        "centered": centered,
        "cycles": cycles,
        "detection": det,
        "status": status(),
    }


def find(
    robot,
    target="person",
    search_speed=DEFAULT_SEARCH_SPEED,
    max_cycles=DEFAULT_MAX_CYCLES,
    detect_timeout=0.8,
):
    _stop.clear()
    target = str(target or "person").strip() or "person"
    min_turn, max_turn = turn_bounds(robot, TURN_MIN, TURN_MAX)
    requested_speed = number(search_speed, min_turn, -max_turn, max_turn)
    speed_sign = -1 if requested_speed < 0 else 1
    speed = speed_sign * max(min_turn, abs(requested_speed))
    cycles = integer(max_cycles, DEFAULT_MAX_CYCLES, 1, 200)
    label, resolve_meta = _target_label(target)
    cx = 0.5

    _state.reset(
        running=True,
        skill="find",
        phase="detect",
        target=target,
        label=label,
        detector=DETECT_URL,
        search_speed=speed,
        max_cycles=cycles,
        **resolve_meta,
    )
    print(
        f"[level2] find start target={target!r} label={label!r} "
        f"speed={speed:g} max_cycles={cycles}",
        flush=True,
    )
    try:
        with robot.vision.exclusive():
            det, cx = _find_once(robot, label, cx, detect_timeout, "precheck")
            _state.update(precheck_seen=bool(det), precheck_box=det.get("box") if det else None)
            if det:
                print(f"[find] precheck found {label} cx={cx:.3f}", flush=True)
                det, centered = _center(robot, target, label, det, cx, detect_timeout)
                if det:
                    out = _found_response(target, label, det, centered, 0)
                    out["precheck_seen"] = True
                    return out
                print("[find] target lost while centering; resuming scan", flush=True)

            for cycle in range(1, cycles + 1):
                if _stop.is_set():
                    break
                cur_min, cur_max = turn_bounds(robot, TURN_MIN, TURN_MAX)
                step_speed = speed_sign * min(cur_max, max(cur_min, abs(requested_speed)))
                print(f"[find] scan {cycle}/{cycles}: turn {step_speed:g} for {TURN_SECONDS:.1f}s", flush=True)
                _state.update(phase="turn", scan_count=cycle, cycle=cycle, seen=False, search_speed=step_speed)
                timed_velocity(
                    robot,
                    _stop,
                    0,
                    step_speed,
                    TURN_SECONDS,
                    "find:search",
                    settle_seconds=SETTLE_SECONDS,
                )
                if _stop.is_set():
                    break

                det, cx = _find_once(robot, label, cx, detect_timeout, cycle)
                if not det:
                    continue
                print(f"[find] detected {label} cx={cx:.3f}; centering", flush=True)
                det, centered = _center(robot, target, label, det, cx, detect_timeout)
                if det:
                    return _found_response(target, label, det, centered, cycle)
                print("[find] target lost while centering; resuming scan", flush=True)

        _state.update(phase="stopped" if _stop.is_set() else "not-found", running=False)
        return {
            "ok": False,
            "skill": "find",
            "target": target,
            "label": label,
            "found": False,
            "cycles": cycles,
            "status": status(),
        }
    except DetectionUnavailable as exc:
        _state.update(running=False)
        return {"ok": False, "skill": "find", "target": target, "label": label,
                "found": False, "cycles": _state.snapshot().get("scan_count", 0),
                "error": str(exc), "status": status()}
    finally:
        robot.movement.stop(source="find")
        _state.update(running=False)


def stop_find():
    _stop.set()
    return status()


def status():
    return _state.snapshot()
