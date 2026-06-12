"""Pi-side lock-on: ask the PC to detect target, then compute motion locally."""
import threading
import time

from perception.vision import DETECT_URL, box_center_x, detect_target, resolve_label

_stop = threading.Event()
_status = {"running": False}


def _clamp(x, lo, hi):
    return max(lo, min(hi, float(x)))


def _turn(err, kp, deadband, stop_deadband, min_turn, max_turn):
    cmd = kp * err
    if abs(err) <= stop_deadband:
        return 0.0
    if abs(cmd) < min_turn:
        span = max(0.001, deadband - stop_deadband)
        boost = _clamp((abs(err) - stop_deadband) / span, 0.0, 1.0)
        floor = min_turn * boost
        if abs(cmd) < floor:
            cmd = floor if (cmd or err) > 0 else -floor
    return _clamp(cmd, -max_turn, max_turn)


def _with_stuck_bonus(turn, err, bonus, max_turn):
    if not turn or not bonus:
        return turn
    return _clamp(turn + (bonus if err > 0 else -bonus), -max_turn, max_turn)


def lock_on(robot, target="person", track_id=None, hz=12, kp=95,
            deadband=0.025, stop_deadband=0.010, min_turn=22, max_turn=42,
            stuck_epsilon=0.006, correction_epsilon=0.010, stuck_frames=2,
            bonus_step=3, max_bonus=18,
            detect_timeout=0.45, cycles=0):
    global _status
    _stop.clear()
    period = 1 / max(1, float(hz))
    cx, loop = 0.5, 0
    last_raw_err, stuck_count, turn_bonus = None, 0, 0.0
    try:
        target_label, resolve_meta = resolve_label(target)
    except Exception as e:
        target_label, resolve_meta = target, {"resolve_error": str(e)}
    _status = {"running": True, "target": target, "label": target_label, "seen": False, "detector": DETECT_URL, **resolve_meta}
    try:
        while not _stop.is_set() and (not cycles or loop < cycles):
            loop += 1
            started = time.time()
            try:
                det, meta = detect_target(robot, target_label, cx, detect_timeout)
            except Exception as e:
                det, meta = None, {"error": str(e)}
            if not det:
                robot.set_velocity(0, 0, source="lock-on")
                _status = {"running": True, "target": target, "label": target_label, "seen": False, "turn": 0, **resolve_meta, **meta}
                time.sleep(max(0, period - (time.time() - started)))
                continue
            z = box_center_x(det["box"])
            raw_err = z - 0.5
            raw_abs = abs(raw_err)
            if raw_abs <= stop_deadband:
                stuck_count, turn_bonus = 0, 0.0
            elif last_raw_err is not None and raw_err * last_raw_err > 0:
                improving = raw_abs < abs(last_raw_err) - correction_epsilon
                stationary = abs(raw_err - last_raw_err) <= stuck_epsilon
                if improving:
                    stuck_count, turn_bonus = 0, 0.0
                elif stationary:
                    stuck_count += 1
                    if stuck_count >= stuck_frames:
                        turn_bonus = min(max_bonus, turn_bonus + bonus_step)
                else:
                    stuck_count = max(0, stuck_count - 1)
            else:
                stuck_count, turn_bonus = 0, 0.0
            last_raw_err = raw_err
            cx = z
            err = cx - 0.5
            turn = _turn(err, kp, deadband, stop_deadband, min_turn, max_turn)
            turn = _with_stuck_bonus(turn, err, turn_bonus, max_turn)
            robot.set_velocity(0, turn, source="lock-on")
            _status = {"running": True, "target": target, "label": target_label, "seen": True, "box": det["box"],
                       "score": det.get("score"), "cx": round(cx, 3),
                       "offset": round(err, 3), "turn": round(turn, 1),
                       "stuck": stuck_count, "turn_bonus": round(turn_bonus, 1),
                       "stop_deadband": stop_deadband, "min_turn": min_turn, **resolve_meta, **meta}
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
