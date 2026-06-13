"""Layer 2 object skills: target resolution and non-actuating servo prototypes."""

from dataclasses import asdict, dataclass
import time

SEARCH_SECONDS = 10.0


def is_pi_track(obj):
    return str(obj.get("source", "")).startswith("pi-")


@dataclass(frozen=True)
class ServoDecision:
    phase: str
    linear: float
    angular: float
    stop_reason: str | None = None

    def dict(self):
        return asdict(self)


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
        if best and is_pi_track(best) and best.get("quality", 0) >= 0.4:
            self.current["phase"] = "found"
            return best
        if best and not allow_motion:
            self.current["phase"] = "visible"
            return best
        if not allow_motion:
            self.current["phase"] = "not-found"
            return None

        while time.time() < end:
            self.current["phase"] = "search-wait" if not allow_motion else "search-spin"
            if allow_motion:
                self.robot.set_velocity(0, 30)
            obj = self.robot.resolve_object(target, prefer_visible=True)
            if obj and is_pi_track(obj) and obj.get("quality", 0) >= 0.4:
                self.robot.stop()
                self.current["phase"] = "found"
                return obj
            time.sleep(0.1)

        self.robot.stop()
        return self.robot.resolve_object(target, prefer_visible=False) or best

    def plan_goto(self, target: str, contact=False):
        obj = self.find(target)
        if not obj:
            self.current["phase"] = "failed"
            return {"ok": False, "error": f"no match for {target!r}"}
        cmd = self.visual_servo_command(obj, contact).dict()
        self.current["phase"] = cmd["phase"]
        return {"ok": True, "target": obj, "command": cmd}

    def step_goto(self, target: str, contact=False, actuate=False):
        plan = self.plan_goto(target, contact)
        if plan.get("ok") and actuate:
            c = plan["command"]
            self.robot.set_velocity(c["linear"], c["angular"])
        return plan

    def goto(self, target: str):
        plan = self.step_goto(target, actuate=False)
        return {**plan, "action": "goto", "prototype_motion": plan.get("command")}

    def push(self, target: str):
        plan = self.step_goto(target, contact=True, actuate=False)
        return {**plan, "action": "push", "prototype_motion": plan.get("command")}

    @staticmethod
    def visual_servo_command(obj, contact=False):
        cx = obj.get("center", (0.5, 0.5))[0]
        error = cx - 0.5
        close = obj.get("distance_proxy", 99) < (2.4 if contact else 3.0)
        age, quality = float(obj.get("age", 99)), float(obj.get("quality", 0))
        if not is_pi_track(obj):
            return ServoDecision("searching", 0, round(error * 25, 1), "not-tracked")
        if age > 0.8 or quality < 0.25:
            return ServoDecision("reacquire", 0, round(error * 25, 1), "stale-track")
        cautious = age > 0.25 or quality < 0.5
        centered = max(0, 1 - abs(error) * 2)
        base = 10 if cautious else 18
        return ServoDecision(
            phase="done"
            if close
            else "centering"
            if abs(error) > 0.15
            else "approaching",
            linear=0
            if close or abs(error) > 0.35
            else round(base * centered * max(0.2, quality), 1),
            angular=round(error * 40, 1),
            stop_reason="close" if close else None,
        )
