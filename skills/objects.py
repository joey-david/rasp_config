"""Layer 2 object skills. Thin for now: resolve target, then later servo/path-plan."""
import time

SEARCH_SECONDS = 10.0


class ObjectSkills:
    def __init__(self, robot):
        self.robot = robot

    def find(self, target: str, timeout=SEARCH_SECONDS):
        end = time.time() + timeout
        best = self.robot.resolve_object(target, prefer_visible=True)
        if best and best["source"] == "visible":
            return best

        while time.time() < end:
            self.robot.set_velocity(0, 18)  # search state: slow spin
            obj = self.robot.resolve_object(target, prefer_visible=True)
            if obj and obj["source"] == "visible":
                self.robot.stop()
                return obj
            time.sleep(0.2)

        self.robot.stop()
        return self.robot.resolve_object(target, prefer_visible=False) or best

    def goto(self, target: str):
        obj = self.find(target)
        if not obj:
            return {"ok": False, "error": f"no match for {target!r}"}
        return {"ok": True, "action": "goto", "target": obj}

    def push(self, target: str):
        obj = self.find(target)
        if not obj:
            return {"ok": False, "error": f"no match for {target!r}"}
        return {"ok": True, "action": "push", "target": obj}
