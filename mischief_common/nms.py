"""IoU-based non-maximum suppression for same-label detection deduplication."""
from .object_geometry import iou


def nms(detections: list[dict], iou_threshold: float = 0.4) -> list[dict]:
    """Suppress same-label detections with high overlap.

    Groups by label, sorts by score descending, keeps highest-scoring
    and removes any lower-scoring box with IoU > threshold.
    """
    if not detections:
        return []

    # Group by label
    by_label: dict[str, list[dict]] = {}
    for d in detections:
        by_label.setdefault(d.get("label", "").lower().strip(), []).append(d)

    kept = []
    for label, items in by_label.items():
        # Sort by score descending
        items.sort(key=lambda d: d.get("score", 0), reverse=True)

        # NMS per label group
        while items:
            best = items.pop(0)
            kept.append(best)
            best_box = best.get("box", [0, 0, 0, 0])
            items = [d for d in items
                     if iou(best_box, d.get("box", [0, 0, 0, 0])) <= iou_threshold]

    # Restore original ordering (by score)
    kept.sort(key=lambda d: d.get("score", 0), reverse=True)
    return kept
