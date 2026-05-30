"""Layer 0 safeguards. For now intentionally a placeholder."""

def edge_detected() -> bool:
    """Placeholder for cliff/edge sensing, use CNN later."""
    return False

def enforce(robot) -> bool:
    # will need to adjust this logic to get the relative angle and distance of the closest edge and only stop if we're probably likely to go over it 
    if robot.direction == "forward" and robot.speed > 0 and edge_detected():
        robot.stop()
        return False
    return True
