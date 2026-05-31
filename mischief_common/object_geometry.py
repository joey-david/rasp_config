"""Normalized object box, spatial, and label helpers."""
from __future__ import annotations

import math

def num(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return default


def clamp_box(raw):
    vals = list(raw or (0, 0, 0, 0))[:4]
    vals += [0] * (4 - len(vals))
    x1, y1, x2, y2 = [num(v) for v in vals]
    if max(x1, y1, x2, y2) > 1.5:
        return None
    x1, x2 = sorted((max(0.0, min(1.0, x1)), max(0.0, min(1.0, x2))))
    y1, y2 = sorted((max(0.0, min(1.0, y1)), max(0.0, min(1.0, y2))))
    return [x1, y1, x2, y2]


def center(box):
    x1, y1, x2, y2 = box
    return [(x1 + x2) / 2, (y1 + y2) / 2]


def area(box):
    x1, y1, x2, y2 = box
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def iou(a, b):
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1, ix2, iy2 = max(ax1, bx1), max(ay1, by1), min(ax2, bx2), min(ay2, by2)
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    union = area(a) + area(b) - inter
    return inter / union if union > 0 else 0.0


def enrich_spatial(obj, hfov_deg=130.0):
    box = clamp_box(obj.get("box"))
    if not box:
        return obj
    cx, _ = center(box)
    dist = 1 / math.sqrt(max(1e-6, area(box)))
    return {
        **obj,
        "box": box,
        "center": [round(cx, 4), round(center(box)[1], 4)],
        "bearing_deg": round((cx - 0.5) * hfov_deg, 1),
        "distance_proxy": round(dist, 2),
    }


def label_score(query, obj, prefer_visible=True):
    q, label = query.lower().strip(), obj["label"].lower().strip()
    base = 1.0 if q == label else 0.0
    if not base and (q in label or label in q):
        base = 0.85
    conf = obj.get("score", 1)
    fresh = 1.0 if obj.get("age", 0) == 0 else max(0, 1 - obj.get("age", 0) / 300)
    bonus = 0.12 if prefer_visible and obj.get("age", 0) == 0 else 0
    return base * (0.65 + 0.35 * conf) * (0.75 + 0.25 * fresh) + bonus
