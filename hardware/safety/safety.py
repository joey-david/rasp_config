"""Layer 0 safeguards. This code must stay local to the Pi."""
from .danger import EdgeSafety

edge_safety = EdgeSafety()
last_veto = ""

def enforce(robot) -> bool:
    global last_veto
    status = edge_safety.check(robot.camera.frame, getattr(robot.camera, "gray", None))
    if robot.direction == "forward" and robot.speed > 0 and status.get("danger"):
        robot.stop()
        last_veto = status.get("reason", "edge danger")
        return False
    last_veto = ""
    return True

def status():
    return {"edge": edge_safety.last, "last_veto": last_veto}
