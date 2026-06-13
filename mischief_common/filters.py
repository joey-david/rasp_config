"""Detection label filters — tag environmental noise without removing it.

Structural labels are never navigation/interaction targets. Detections with
these labels still flow through the pipeline (for display, mapping context)
but are skipped by skills.
"""

# Labels that are structural environment — never actionable targets.
# Keep the full detector vocabulary; this only gates skill use.
ENVIRONMENTAL: set[str] = {
    "wall",
    "floor",
    "ceiling",
    "blind",
    "rug",
    "mat",
    "stairs",
    "step",
    "ledge",
    "edge",
    "outlet",
    "ceiling fan",
    "chandelier",
    "faucet",
}


def is_environmental(label: str) -> bool:
    """Check if a label is structural background noise."""
    return label.lower().strip() in ENVIRONMENTAL


def filter_actionable(detections: list[dict]) -> list[dict]:
    """Return only non-environmental detections."""
    return [d for d in detections if not is_environmental(d.get("label", ""))]
