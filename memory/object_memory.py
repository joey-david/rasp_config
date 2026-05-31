"""Recent object memory with semantic and crude spatial hints."""
from collections import OrderedDict
import time
from .spatial import enrich

ALIASES = {
    "human": {"person"}, "man": {"person"}, "woman": {"person"}, "kid": {"person"},
    "stool": {"chair"}, "seat": {"chair", "sofa"}, "sofa": {"couch"},
    "table": {"dining table"}, "desk": {"dining table"},
    "mug": {"cup"}, "glass": {"cup", "wine glass"}, "drink": {"cup", "bottle"},
    "phone": {"cell phone"}, "mobile": {"cell phone"},
}

def center(box):
    x1, y1, x2, y2 = box
    return ((x1 + x2) / 2, (y1 + y2) / 2)

class ObjectMemory:
    def __init__(self, max_items=128, ttl=300):
        self.max_items, self.ttl = max_items, ttl
        self.items = OrderedDict()

    def remember(self, d):
        now = time.time()
        raw = d if isinstance(d, dict) else d.dict()
        box = tuple(raw.get("box") or (0, 0, 0, 0))
        label = str(raw.get("label", "")).strip()
        track = raw.get("track_id") or raw.get("id")
        cx, cy = center(box)
        key = str(track or f"{label}:{cx:.1f}:{cy:.1f}")
        self.items[key] = enrich({
            **raw,
            "label": label,
            "score": float(raw.get("score", raw.get("confidence", 1.0))),
            "box": box,
            "last_seen": now,
            "source": raw.get("source", "memory"),
        })
        self.items.move_to_end(key)
        self.prune()

    def update(self, detections):
        for d in detections:
            self.remember(d)

    def prune(self):
        now = time.time()
        for k, v in list(self.items.items()):
            if now - v["last_seen"] > self.ttl:
                del self.items[k]
        while len(self.items) > self.max_items:
            self.items.popitem(last=False)

    def inventory(self):
        self.prune()
        now = time.time()
        return [{**v, "age": round(now - v["last_seen"], 1)} for v in reversed(self.items.values())]

    def resolve(self, query, visible=(), prefer_visible=True):
        visible = [enrich({**d, "age": 0}) for d in visible or []]
        candidates = visible + self.inventory()
        scored = [(self.match(query, c, prefer_visible), c) for c in candidates]
        scored = [(s, c) for s, c in scored if s > 0.45]
        if not scored:
            return None
        score, obj = max(scored, key=lambda x: x[0])
        return {**obj, "match": round(score, 3), "query": query}

    @staticmethod
    def match(query, obj, prefer_visible=True):
        q, label = query.lower().strip(), obj["label"].lower().strip()
        names = {q, *ALIASES.get(q, set())}
        labels = {label, *(a.lower() for a in obj.get("aliases", []))}
        base = 1.0 if names & labels else 0.0
        if not base and q in label:
            base = 0.85
        conf = obj.get("score", 1)
        fresh = 1.0 if obj.get("age", 0) == 0 else max(0, 1 - obj.get("age", 0) / 300)
        bonus = 0.12 if prefer_visible and obj.get("age", 0) == 0 else 0
        return base * (0.65 + 0.35 * conf) * (0.75 + 0.25 * fresh) + bonus
