"""Detection label filters — tag environmental noise without removing it.

Structural labels are never navigation/interaction targets. Detections with
these labels still flow through the pipeline (for display, mapping context)
but are skipped by skills and excluded from memory.
"""

# Labels that are structural environment — never actionable targets.
# Keep the full YOLO-World vocabulary; this only gates skill/memory use.
ENVIRONMENTAL: set[str] = {
    "wall", "floor", "ceiling", "door", "window",
    "curtain", "blind", "carpet", "rug", "mat",
    "stairs", "step", "ledge", "edge", "obstacle",
    "baseboard", "outlet", "switch",
    "light", "lamp", "ceiling fan", "chandelier",
    "cabinet", "shelf", "drawer", "handle",
    "mirror", "clock",
    "sink", "toilet", "bathtub", "faucet", "shower",
    "towel",  # usually hanging, not a target
}


def is_environmental(label: str) -> bool:
    """Check if a label is structural background noise."""
    return label.lower().strip() in ENVIRONMENTAL


def filter_actionable(detections: list[dict]) -> list[dict]:
    """Return only non-environmental detections."""
    return [d for d in detections if not is_environmental(d.get("label", ""))]


def tag_all(detections: list[dict]) -> list[dict]:
    """Add 'environmental' flag to each detection. Does not remove any."""
    return [{**d, "environmental": is_environmental(d.get("label", ""))} for d in detections]
