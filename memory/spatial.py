"""Tiny monocular spatial hints: bearing from image x, distance from box size."""
import math


def enrich(obj, hfov_deg=130.0):
    box = obj.get("box") or (0, 0, 0, 0)
    x1, y1, x2, y2 = box
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    area = max(1e-6, (x2 - x1) * (y2 - y1))
    bearing = (cx - 0.5) * hfov_deg
    distance_proxy = 1 / math.sqrt(area)
    return {
        **obj,
        "center": (round(cx, 3), round(cy, 3)),
        "bearing_deg": round(bearing, 1),
        "distance_proxy": round(distance_proxy, 2),
    }
