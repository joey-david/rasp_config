"""Pi-side lock-on: ask the PC to detect target, then compute motion locally."""

import json
import os
import threading
import time
import urllib.parse
import urllib.request

_stop = threading.Event()
_status = {"running": False}

DETECT_URL = os.getenv("PC_DETECT_URL", "http://192.168.0.24:8081/detect")


def _clamp(x, lo, hi):
    return max(lo, min(hi, float(x)))


def _center(box):
    return (float(box[0]) + float(box[2])) * 0.5


def _sgn(x):
    return 1 if x > 0 else -1 if x < 0 else 0


def _slew(cur, target, step):
    return cur + _clamp(target - cur, -step, step)


def _best(detections, last_cx):
    best, best_score = None, -1

    for d in detections or []:
        box = d.get("box") or []
        if len(box) != 4:
            continue

        cx = _center(box)
        score = float(d.get("score") or 0.5) - 0.35 * abs(cx - last_cx)

        if score > best_score:
            best, best_score = d, score

    return best


def _detect(robot, target, timeout):
    frame, captured_at, frame_id = robot.camera.latest()
    if not frame:
        return [], {"error": "no frame"}

    url = DETECT_URL + "?" + urllib.parse.urlencode({"label": target})

    req = urllib.request.Request(
        url,
        data=frame,
        method="POST",
        headers={
            "Content-Type": "image/jpeg",
            "X-Captured-At": str(captured_at),
            "X-Frame-Id": str(frame_id),
        },
    )

    t0 = time.time()

    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = json.loads(r.read().decode())

    detections = out.get("detections") or []

    robot.ingest_detections(
        {
            "source": "pc-detect-request",
            "model": out.get("model"),
            "frame_id": frame_id,
            "captured_at": captured_at,
            "inferred_at": out.get("inferred_at", time.time()),
            "sent_at": time.time(),
            "detections": detections,
            "pc_timing": {
                "snapshot_started_at": captured_at,
                "snapshot_received_at": t0,
                "infer_done_at": out.get("inferred_at", time.time()),
                "sent_at": time.time(),
            },
        }
    )

    return detections, {
        "infer_ms": out.get("infer_ms"),
        "frame_id": frame_id,
        "captured_at": captured_at,
        "age_ms": round((time.time() - captured_at) * 1000),
    }


def _turn(err, derr, boost, kp, kd, stop_deadband, max_turn):
    if abs(err) <= stop_deadband:
        return 0.0

    cmd = kp * err + kd * derr
    cmd += boost * _sgn(err)

    return _clamp(cmd, -max_turn, max_turn)


def lock_on(
    robot,
    target="person",
    track_id=None,
    hz=15,
    kp=70,
    kd=18,
    stop_deadband=0.018,
    boost_err=0.04,
    boost_improve=0.006,
    boost_step=2.5,
    boost_decay=0.35,
    boost_max=30,
    max_turn=50,
    slew=7,
    detect_timeout=0.45,
    cycles=0,
):
    global _status

    _stop.clear()

    period = 1 / max(1, float(hz))
    loop = 0

    cx = 0.5
    last_err = None
    boost = 0.0
    turn = 0.0

    _status = {
        "running": True,
        "target": target,
        "seen": False,
        "detector": DETECT_URL,
    }

    try:
        while not _stop.is_set() and (not cycles or loop < cycles):
            loop += 1
            started = time.time()

            try:
                detections, meta = _detect(robot, target, detect_timeout)
                det = _best(detections, cx)
            except Exception as e:
                det, meta = None, {"error": str(e)}

            if not det:
                boost = 0.0
                last_err = None
                turn = _slew(turn, 0.0, slew)

                robot.set_velocity(0, turn, source="lock-on")

                _status = {
                    "running": True,
                    "target": target,
                    "seen": False,
                    "turn": round(turn, 1),
                    **meta,
                }

                time.sleep(max(0, period - (time.time() - started)))
                continue

            cx = _center(det["box"])
            err = cx - 0.5
            abs_err = abs(err)

            derr = 0.0 if last_err is None else err - last_err
            improving = last_err is not None and abs_err < abs(last_err) - boost_improve

            if abs_err <= stop_deadband:
                boost = 0.0
            elif abs_err >= boost_err and not improving:
                boost = min(boost_max, boost + boost_step)
            else:
                boost *= boost_decay

            wanted = _turn(
                err=err,
                derr=derr,
                boost=boost,
                kp=kp,
                kd=kd,
                stop_deadband=stop_deadband,
                max_turn=max_turn,
            )

            turn = _slew(turn, wanted, slew)

            robot.set_velocity(0, turn, source="lock-on")

            last_err = err

            _status = {
                "running": True,
                "target": target,
                "seen": True,
                "box": det["box"],
                "score": det.get("score"),
                "cx": round(cx, 3),
                "offset": round(err, 3),
                "derr": round(derr, 3),
                "turn": round(turn, 1),
                "wanted": round(wanted, 1),
                "boost": round(boost, 1),
                "stop_deadband": stop_deadband,
                **meta,
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
