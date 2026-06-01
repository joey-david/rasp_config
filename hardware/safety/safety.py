"""Layer 0 safeguards — local Pi-only, no PC dependency.

Edge detection uses the camera's grayscale frame buffer (320x240)
which is already produced for the tracker — zero extra camera cost.
"""

from .danger import EdgeDetector

_edge = EdgeDetector(enabled=False)
_last_veto = ""


def enforce(robot) -> bool:
    """Check safety. Returns True if safe, False if motion was vetoed."""
    global _last_veto
    gray = getattr(robot.camera, "gray", None)
    status = _edge.check(gray)

    if robot.direction == "forward" and robot.speed > 0 and status.get("danger"):
        robot.stop()
        _last_veto = status.get("reason", "edge danger")
        return False

    _last_veto = ""
    return True


def status() -> dict:
    return {"edge": _edge.last, "last_veto": _last_veto}


def reset_edge():
    """Clear edge detector history (call after repositioning robot)."""
    _edge.reset()
