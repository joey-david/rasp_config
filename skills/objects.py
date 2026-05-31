"""Layer 2 object skills: target resolution and non-actuating servo prototypes."""
import time

SEARCH_SECONDS = 10.0


class ObjectSkills:
    def __init__(self, robot):
        self.robot = robot
        self.current = {"skill": None, "phase": "idle", "target": None}

    def status(self):
        return {"layer2": self.current}

    def find(self, target: str, timeout=SEARCH_SECONDS, allow_motion=False):
        end = time.time() + timeout
        self.current = {"skill": "find", "phase": "resolve", "target": target}
        best = self.robot.resolve_object(target, prefer_visible=True)
        if best and best.get("age", 1) == 0:
            self.current["phase"] = "found"
            return best
        if best and not allow_motion:
            self.current["phase"] = "memory"
            return best
        if not allow_motion:
            self.current["phase"] = "not-found"
            return None

        while time.time() < end:
            self.current["phase"] = "search-wait" if not allow_motion else "search-spin"
            if allow_motion:
                self.robot.set_velocity(0, 18)
            obj = self.robot.resolve_object(target, prefer_visible=True)
            if obj and obj.get("age", 1) == 0:
                self.robot.stop()
                self.current["phase"] = "found"
                return obj
            time.sleep(0.2)

        self.robot.stop()
        return self.robot.resolve_object(target, prefer_visible=False) or best

    def goto(self, target: str):
        obj = self.find(target)
        if not obj:
            self.current["phase"] = "failed"
            return {"ok": False, "error": f"no match for {target!r}"}
        cmd = self.visual_servo_command(obj)
        return {"ok": True, "action": "goto", "target": obj, "prototype_motion": cmd}

    def push(self, target: str):
        obj = self.find(target)
        if not obj:
            self.current["phase"] = "failed"
            return {"ok": False, "error": f"no match for {target!r}"}
        cmd = self.visual_servo_command(obj, contact=True)
        return {"ok": True, "action": "push", "target": obj, "prototype_motion": cmd}

    @staticmethod
    def visual_servo_command(obj, contact=False):
        cx = obj.get("center", (0.5, 0.5))[0]
        error = cx - 0.5
        close = obj.get("distance_proxy", 99) < (2.4 if contact else 3.0)
        return {
            "linear": 0 if close else round(max(0, 18 * (1 - abs(error) * 2)), 1),
            "angular": round(error * 40, 1),
            "stop_reason": "close" if close else None,
        }
