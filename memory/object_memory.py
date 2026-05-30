"""LRU semantic object memory."""
from collections import OrderedDict
from difflib import SequenceMatcher
import time

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
        box = tuple(d.box)
        cx, cy = center(box)
        key = f"{d.label}:{cx:.1f}:{cy:.1f}"
        self.items[key] = {
            "label": d.label,
            "score": float(d.score),
            "box": box,
            "center": (round(cx, 3), round(cy, 3)),
            "last_seen": now,
            "source": "memory",
        }
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
        visible = [
            {
                "label": d.label,
                "score": d.score,
                "box": d.box,
                "center": center(d.box),
                "age": 0,
                "source": "visible",
            }
            for d in visible
        ]
        candidates = visible + self.inventory()
        scored = [
            (self.match(query, c, prefer_visible), c)
            for c in candidates
        ]
        scored = [(s, c) for s, c in scored if s > 0.28]
        if not scored:
            return None
        score, obj = max(scored, key=lambda x: x[0])
        return {**obj, "match": round(score, 3), "query": query}

    @staticmethod
    def match(query, obj, prefer_visible=True):
        q, label = query.lower().strip(), obj["label"].lower().strip()
        names = {q, *ALIASES.get(q, set())}
        base = 1.0 if label in names else SequenceMatcher(None, q, label).ratio()
        conf = obj.get("score", 1)
        fresh = 1.0 if obj["source"] == "visible" else max(0, 1 - obj.get("age", 0) / 300)
        bonus = 0.12 if prefer_visible and obj["source"] == "visible" else 0
        return base * (0.65 + 0.35 * conf) * (0.75 + 0.25 * fresh) + bonus