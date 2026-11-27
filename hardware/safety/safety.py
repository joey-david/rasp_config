"""Continuously enforced Pi-local safeguards."""

import os
import threading
import time

from .danger import EdgeDetector

_edge = EdgeDetector(enabled=os.getenv("EDGE_SAFETY_ENABLED", "1").lower() not in {"0", "false", "no"})
_last_veto = ""
_stop = threading.Event()
_thread = None
_last_edge_signature = None
_moving_at = 0.0
# The baseline must come from a robot at rest, not from the pauses between a
# skill's pulses, or a slow approach toward an edge teaches it the edge.
LEARN_IDLE_SECONDS = 1.0


def _idle_for_learning(robot):
    global _moving_at
    now = time.monotonic()
    if robot.motion.left or robot.motion.right:
        _moving_at = now
        return False
    skill_active = getattr(robot, "skill_active", None)
    try:
        if skill_active and skill_active():
            _moving_at = now
            return False
    except Exception:
        return False
    return now - _moving_at >= LEARN_IDLE_SECONDS


def check(robot, learn=None):
    return _edge.check(
        getattr(robot.camera, "gray", None),
        getattr(robot.camera, "gray_at", None),
        learn=_idle_for_learning(robot) if learn is None else bool(learn),
    )


def _monitor_dead():
    return _thread is not None and not _thread.is_alive() and not _stop.is_set()


def command_allowed(robot, linear):
    """Reverse and in-place turns are always available for edge recovery."""
    global _last_veto
    if float(linear) <= 0:
        _last_veto = ""
        return True
    if _monitor_dead():
        veto = "safety monitor stopped"
        if veto != _last_veto:
            print(f"[level0] forward veto: {veto}", flush=True)
        _last_veto = veto
        return False
    edge = check(robot, learn=False)
    if not edge.get("enabled", True):
        _last_veto = ""
        return True
    if edge.get("ready") and not edge.get("danger"):
        _last_veto = ""
        return True
    veto = edge.get("reason", "edge safety unavailable")
    if veto != _last_veto:
        print(f"[level0] forward veto: {veto}", flush=True)
    _last_veto = veto
    return False


def enforce(robot, requested_linear=None):
    linear = robot.motion.linear if requested_linear is None else float(requested_linear)
    if command_allowed(robot, linear):
        return True
    halt = getattr(robot, "_safety_stop", robot.motion.stop)
    halt()
    robot.control = {"mode": "idle", "keys": "", "source": "safety-edge"}
    return False


def _monitor(robot):
    global _last_edge_signature
    last_error = None
    while not _stop.wait(0.05):
        # One failed tick (e.g. a transient GPIO error while halting) must not
        # kill the monitor; the halt is retried on the next tick.
        try:
            edge = check(robot)
            signature = (edge.get("ready"), edge.get("danger"), edge.get("reason"))
            if signature != _last_edge_signature:
                print(
                    f"[level0] edge ready={bool(edge.get('ready'))} "
                    f"danger={bool(edge.get('danger'))} reason={edge.get('reason')}",
                    flush=True,
                )
                _last_edge_signature = signature
            if edge.get("enabled", True) and robot.motion.linear > 0 and (edge.get("danger") or not edge.get("ready")):
                enforce(robot, robot.motion.linear)
            last_error = None
        except Exception as exc:
            if repr(exc) != last_error:
                print(f"[level0] monitor error: {exc!r}", flush=True)
            last_error = repr(exc)


def start(robot):
    global _last_edge_signature, _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _last_edge_signature = None
    _thread = threading.Thread(target=_monitor, args=(robot,), daemon=True, name="safety-monitor")
    _thread.start()
    print(f"[level0] safety monitor started edge_enabled={_edge.enabled}", flush=True)


def stop():
    _stop.set()


def reset():
    global _last_edge_signature, _last_veto
    _edge.reset()
    _last_edge_signature = None
    _last_veto = ""


def status():
    return {"edge": dict(_edge.last), "last_veto": _last_veto, "monitoring": bool(_thread and _thread.is_alive())}
