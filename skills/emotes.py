"""Small movement emote templates."""

import time


TEMPLATES = {
    "nod": [(18, 0, 0.12), (-18, 0, 0.12), (0, 0, 0.05)],
    "shake": [(0, 28, 0.12), (0, -28, 0.24), (0, 28, 0.12), (0, 0, 0.05)],
    "wiggle": [(12, 22, 0.12), (12, -22, 0.12), (-10, 0, 0.10), (0, 0, 0.05)],
    "backoff": [(-22, 0, 0.20), (0, 0, 0.05)],
}


def names():
    return sorted(TEMPLATES)


def run(robot, name, scale=1.0):
    steps = TEMPLATES.get(str(name or "").strip().lower())
    if not steps:
        return {"ok": False, "error": f"unknown emote {name!r}", "emotes": names()}
    scale = max(0.25, min(2.0, float(scale)))
    try:
        for linear, angular, seconds in steps:
            robot.set_velocity(linear, angular, source=f"emote:{name}")
            time.sleep(seconds * scale)
    finally:
        robot.stop(source=f"emote:{name}")
    return {"ok": True, "emote": name, "scale": scale}
