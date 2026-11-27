"""Sense-plan-act controller that exposes only bounded robot skills."""

import os
import threading

from perception.vision import capture_detect_all
from skills import emotes
from skills.find import stop_find

from .remote import RemotePlanner

DEFAULT_GOAL = (
    "Explore and perform one harmless, reversible bit of mischief. "
    "Do not touch living beings, fragile objects, edges, or hazards."
)
ALLOWED = {
    "observe": (),
    "find": ("target",),
    "go_to": ("target",),
    "push": ("target",),
    "push_to": ("source", "destination"),
    "emote": ("name",),
    "wait": (),
    "stop": (),
}


class AutonomyController:
    def __init__(self, robot, planner=None):
        self.robot = robot
        self.planner = planner or RemotePlanner()
        self.allow_contact = os.getenv("AUTONOMY_ALLOW_CONTACT", "0").lower() in {"1", "true", "yes"}
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.RLock()
        self._state = {"running": False, "phase": "idle", "trace": []}

    def status(self):
        with self._lock:
            return {**self._state, "planner": self.planner.status(), "allow_contact": self.allow_contact}

    def _update(self, **items):
        with self._lock:
            self._state = {**self._state, **items}

    def start(self, goal=None, max_steps=12):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return {"ok": False, "error": "autonomy already running", "status": self.status()}
            self._stop.clear()
            goal = str(goal or DEFAULT_GOAL).strip()[:1000]
            max_steps = max(1, min(50, int(max_steps)))
            self._state = {
                "running": True, "phase": "starting", "goal": goal,
                "step": 0, "max_steps": max_steps, "trace": [], "error": "",
            }
            self._thread = threading.Thread(
                target=self._run, args=(goal, max_steps), daemon=True, name="autonomy"
            )
            print(f"[level3] autonomy start goal={goal!r} max_steps={max_steps}", flush=True)
            self._thread.start()
        return {"ok": True, "status": self.status()}

    def stop(self):
        self._stop.set()
        stop_find()
        emotes.stop_emote()
        self.robot.skills.stop()
        self.robot.stop(source="autonomy:stop")
        running = bool(self._thread and self._thread.is_alive())
        self._update(phase="stopping" if running else "stopped")
        return {"ok": True, "status": self.status()}

    def _observation(self):
        state = self.robot.status(force=True)
        detections = [
            {
                key: det.get(key)
                for key in ("label", "score", "box", "center", "relative_depth", "quality", "age")
            }
            for det in state["perception"]["detections"]
        ]
        return {
            "detections": detections,
            "map": state["map"],
            "safety": state["safety"],
            "motion": {"direction": state["motion"]["direction"]},
            "constraints": {
                "one_action_per_step": True,
                "contact_enabled": self.allow_contact,
                "depth_is_metric": False,
                "allowed_actions": {name: list(args) for name, args in ALLOWED.items()},
                "emotes": emotes.names(),
            },
            "recent_actions": self._state.get("trace", [])[-4:],
        }

    def _sense(self):
        with self.robot.vision.exclusive():
            self.robot.stop(source="autonomy:observe")
            if self._stop.wait(float(os.getenv("AUTONOMY_SETTLE_SECONDS", "0.15"))):
                return None, None
            frame, detections, meta = capture_detect_all(self.robot, timeout=2.0)
            observation = self._observation()
        print(
            f"[stack] sense frame={meta.get('frame_id')} detections={len(detections)} "
            f"infer_ms={meta.get('infer_ms')}",
            flush=True,
        )
        return frame, observation

    @staticmethod
    def _validate(raw):
        if not isinstance(raw, dict):
            raise ValueError("planner action must be an object")
        name = str(raw.get("action") or "").strip()
        if name not in ALLOWED:
            raise ValueError(f"unsupported planner action {name!r}")
        action = {"action": name}
        for key in ALLOWED[name]:
            value = str(raw.get(key) or "").strip()
            if not value:
                raise ValueError(f"{name} requires {key}")
            if len(value) > 80:
                raise ValueError(f"{name} {key} is too long")
            action[key] = value
        if name == "wait":
            action["seconds"] = max(0.0, min(5.0, float(raw.get("seconds", 1.0))))
        if name == "stop":
            action["reason"] = str(raw.get("reason") or "planner finished")[:240]
        return action

    def _execute(self, action):
        name = action["action"]
        if name == "observe":
            return {"ok": True, "observed": True}
        if name == "find":
            return self.robot.find(action["target"])
        if name == "go_to":
            return self.robot.goto(action["target"])
        if name in {"push", "push_to"} and not self.allow_contact:
            return {"ok": False, "error": "autonomous contact is disabled"}
        if name == "push":
            return self.robot.push(action["target"])
        if name == "push_to":
            return self.robot.push_to(action["source"], action["destination"])
        if name == "emote":
            return self.robot.emote(action["name"])
        if name == "wait":
            self._stop.wait(action["seconds"])
            return {"ok": not self._stop.is_set(), "waited": action["seconds"]}
        return {"ok": True, "done": True, "reason": action.get("reason")}

    @staticmethod
    def _compact(result):
        return {
            key: result.get(key)
            for key in ("ok", "action", "found", "centered", "error", "reason", "cycles")
            if result.get(key) is not None
        }

    def _run(self, goal, max_steps):
        failures = 0
        try:
            state = self.robot.status(force=True)
            edge = state["safety"].get("edge", {})
            print(
                f"[stack] level0 edge_ready={bool(edge.get('ready'))} "
                f"danger={bool(edge.get('danger'))} reason={edge.get('reason')}",
                flush=True,
            )
            print(
                f"[stack] level1 motion={state['motion'].get('direction')} watchdog="
                f"{state['motion'].get('watchdog_alive')}",
                flush=True,
            )
            print("[stack] level2 skills=find,go_to,push,push_to,follow,emote", flush=True)
            print(
                f"[stack] perception detections={len(state['perception'].get('detections') or [])} "
                f"map_objects={len(state['map'].get('objects') or [])} metric={state['map'].get('metric')}",
                flush=True,
            )
            print(f"[stack] level3 planner={self.planner.status().get('url', 'local')}", flush=True)
            for step in range(1, max_steps + 1):
                if self._stop.is_set():
                    break
                self._update(phase="planning", step=step)
                frame, observation = self._sense()
                if frame is None:
                    break
                proposed = self.planner.plan(goal, observation, frame)
                if self._stop.is_set():
                    print("[level3] discarded planner response after stop", flush=True)
                    break
                action = self._validate(proposed)
                print(f"[autonomy] step {step}/{max_steps}: {action}", flush=True)
                self._update(phase="acting", action=action)
                result = self._execute(action)
                print(f"[autonomy] result: {self._compact(result)}", flush=True)
                entry = {"step": step, "action": action, "result": self._compact(result)}
                trace = self._state.get("trace", []) + [entry]
                self._update(trace=trace[-20:])
                failures = failures + 1 if result.get("ok") is False else 0
                if action["action"] == "stop":
                    self._update(phase="complete")
                    break
                if failures >= 3:
                    raise RuntimeError("three consecutive actions failed")
            else:
                self._update(phase="step-limit")
        except Exception as exc:
            self._update(phase="failed", error=str(exc))
        finally:
            self.robot.stop(source="autonomy:done")
            if self._stop.is_set() and self._state.get("phase") not in {"complete", "failed"}:
                self._update(phase="stopped")
            self._update(running=False)
