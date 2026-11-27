"""Bounded layer-2 visual navigation and object-contact skills."""

import math
import threading
import time

from mischief_common.filters import is_environmental
from mischief_common.object_geometry import box_metrics, iou
from perception.vision import (
    box_center_x,
    detect_all,
    detect_pair_samples,
    detect_target_samples,
    resolve_label,
)
from skills.runtime import forward_bounds, turn_bounds
from skills.tuning import FORWARD_MIN, TURN_KP, TURN_MAX, TURN_MIN

FORWARD_POWER = FORWARD_MIN
SETTLE_SECONDS = 0.15
MAX_CYCLES = 24
CENTER_TOLERANCE = 0.065
GOTO_SCALE = 0.43
CONTACT_SCALE = 0.60
PUSH_TO_CYCLES = 12
PUSH_TO_PULSE = 0.20
PUSH_TO_GAP = 0.04

NO_CONTACT = {
    "person", "bird", "cat", "dog", "horse", "sheep", "cow", "elephant",
    "bear", "zebra", "giraffe",
}


def _scale(det):
    return box_metrics(det["box"])["scale"]


def _box_gap(a, b):
    horizontal = max(0.0, max(a[0], b[0]) - min(a[2], b[2]))
    vertical = max(0.0, max(a[1], b[1]) - min(a[3], b[3]))
    return math.hypot(horizontal, vertical)


class ObjectSkills:
    def __init__(self, robot):
        self.robot = robot
        self.current = {"skill": None, "phase": "idle", "target": None}
        self._stop = threading.Event()
        self._run_lock = threading.RLock()

    def status(self):
        return {"layer2": dict(self.current)}

    def stop(self):
        self._stop.set()
        self.robot.stop(source="level2:stop")
        phase = "stopping" if self.current.get("running") else "stopped"
        self.current = {**self.current, "phase": phase}
        return self.status()

    @staticmethod
    def _resolve(target):
        target = str(target or "").strip()
        if not target:
            raise ValueError("target is required")
        label, meta = resolve_label(target)
        if is_environmental(label):
            raise ValueError(f"{label!r} is not an actionable object")
        return target, label, meta

    def _update(self, **values):
        self.current = {**self.current, **values}
        return self.current

    def _pulse(self, linear, angular, seconds, phase):
        if self._stop.is_set():
            return False, "stopped"
        self._update(phase=phase, linear=round(linear, 1), turn=round(angular, 1))
        print(
            f"[level2] {phase}: linear={linear:.1f} angular={angular:.1f} "
            f"duration={seconds:.2f}s",
            flush=True,
        )
        result = self.robot.set_velocity(linear, angular, source=f"level2:{phase}")
        if result.get("ok") is False:
            return False, result.get("veto", "motion vetoed")
        self._stop.wait(seconds)
        self.robot.stop(source=f"level2:{phase}")
        if not self._stop.is_set():
            self._stop.wait(SETTLE_SECONDS)
        return not self._stop.is_set(), ""

    def _turn_pulse(self, error):
        min_turn, max_turn = turn_bounds(self.robot, TURN_MIN, TURN_MAX)
        turn = self.robot.movement.turn(
            error, TURN_KP, CENTER_TOLERANCE, 0.015, min_turn, max_turn
        )
        seconds = max(0.10, min(0.28, abs(error) * 0.72))
        return self._pulse(0, turn, seconds, "centering")

    def _await_live_stream(self, since, timeout=3.0):
        camera = getattr(self.robot, "camera", None)
        if getattr(camera, "gray_at", None) is None:
            return
        end = time.time() + timeout
        while (camera.gray_at or 0) <= since and time.time() < end:
            if self._stop.wait(0.03):
                return

    def _forward_power(self):
        return forward_bounds(self.robot, FORWARD_POWER)[0]

    def _acquire(self, target, label):
        det, meta = detect_target_samples(self.robot, label, attempts=3, timeout=1.5)
        if det:
            return det, meta
        if self._stop.is_set():
            return None, meta
        self._update(phase="finding")
        found = self.robot.find(target, search_speed=35, max_cycles=15)
        return found.get("detection"), found.get("status", {})

    def _blocked(self, target_label, ignored=()):
        counts = {}
        for _ in range(3):
            try:
                detections, _ = detect_all(self.robot, timeout=1.0)
            except Exception as exc:
                self._update(error=str(exc))
                return "vision unavailable"
            seen = set()
            for raw in detections:
                det = {**raw, **box_metrics(raw["box"])}
                label = det.get("label", "")
                center = det.get("center") or (0.5, 0.5)
                if label == target_label or label in ignored or is_environmental(label):
                    continue
                if abs(center[0] - 0.5) < 0.16 and _scale(det) >= 0.48:
                    seen.add(label)
            for label in seen:
                counts[label] = counts.get(label, 0) + 1
        return next((label for label, count in counts.items() if count >= 2), None)

    def _approach(self, target, label, contact=False, ignored=()):
        det, meta = self._acquire(target, label)
        if not det:
            return None, 0, meta, "target not found"

        with self.robot.vision.exclusive():
            for cycle in range(1, MAX_CYCLES + 1):
                if self._stop.is_set():
                    return det, cycle - 1, meta, "stopped"
                if cycle > 1:
                    det, meta = detect_target_samples(
                        self.robot, label, box_center_x(det["box"]), attempts=3, timeout=1.5
                    )
                    if not det:
                        if self._stop.is_set():
                            return None, cycle - 1, meta, "stopped"
                        self._update(phase="reacquire", seen=False)
                        found = self.robot.find(target, search_speed=35, max_cycles=5)
                        det = found.get("detection")
                        meta = found.get("status", meta)
                        if not det:
                            return None, cycle - 1, meta, "target lost"

                cx = box_center_x(det["box"])
                error, scale = cx - 0.5, _scale(det)
                # find()'s status snapshot reuses these keys; explicit values win.
                self._update(**{
                    **meta, "cycle": cycle, "seen": True, "box": det["box"],
                    "score": det.get("score"), "offset": round(error, 3),
                    "scale": round(scale, 3),
                })
                threshold = CONTACT_SCALE if contact else GOTO_SCALE
                close_by_bottom = det["box"][3] >= (0.96 if contact else 0.90) and scale >= 0.25
                if scale >= threshold or close_by_bottom:
                    # Contact decisions get one slow, maximum-resolution check.
                    if contact:
                        captured = time.time()
                        confirmed, final_meta = detect_target_samples(
                            self.robot, label, cx, attempts=3, timeout=12, maximum=True
                        )
                        # Full-resolution stills pause the stream; Level 0 vetoes
                        # forward motion until a fresh grayscale frame arrives.
                        self._await_live_stream(captured)
                        if not confirmed:
                            return det, cycle, final_meta, "contact position not confirmed"
                        det, scale = confirmed, _scale(confirmed)
                        if scale < CONTACT_SCALE and confirmed["box"][3] < 0.96:
                            continue
                    self._update(phase="at-target", scale=round(scale, 3))
                    return det, cycle, meta, ""

                if abs(error) > CENTER_TOLERANCE:
                    ok, reason = self._turn_pulse(error)
                else:
                    blocker = self._blocked(label, ignored)
                    if blocker:
                        return det, cycle, meta, f"path blocked by {blocker}"
                    ok, reason = self._pulse(self._forward_power(), 0, 0.18, "approaching")
                if not ok:
                    return det, cycle, meta, reason
        return det, MAX_CYCLES, meta, "approach cycle limit"

    def goto(self, target):
        return self.go_to(target)

    def go_to(self, target):
        with self._run_lock:
            self._stop.clear()
            try:
                target, label, resolve_meta = self._resolve(target)
            except Exception as exc:
                return {"ok": False, "action": "go_to", "error": str(exc)}
            self.current = {
                "running": True, "skill": "go_to", "phase": "acquire",
                "target": target, "label": label, **resolve_meta,
            }
            print(f"[level2] go_to start target={target!r} label={label!r}", flush=True)
            try:
                det, cycles, meta, error = self._approach(target, label)
                return {
                    "ok": not error, "action": "go_to", "target": target,
                    "label": label, "cycles": cycles, "detection": det,
                    "error": error or None, "vision": meta,
                }
            finally:
                self.robot.stop(source="level2:go_to")
                self._update(running=False, phase="failed" if self.current.get("phase") != "at-target" else "done")

    def push(self, target):
        with self._run_lock:
            self._stop.clear()
            try:
                target, label, resolve_meta = self._resolve(target)
            except Exception as exc:
                return {"ok": False, "action": "push", "error": str(exc)}
            if label in NO_CONTACT:
                return {"ok": False, "action": "push", "error": f"contact with {label!r} is not allowed"}
            self.current = {
                "running": True, "skill": "push", "phase": "acquire",
                "target": target, "label": label, **resolve_meta,
            }
            print(f"[level2] push start target={target!r} label={label!r}", flush=True)
            try:
                det, cycles, meta, error = self._approach(target, label, contact=True)
                if not error:
                    ok, error = self._pulse(self._forward_power(), 0, 0.32, "push")
                    if ok:
                        self._update(phase="done")
                return {
                    "ok": not error, "action": "push", "target": target,
                    "label": label, "cycles": cycles, "detection": det,
                    "error": error or None, "vision": meta,
                }
            finally:
                self.robot.stop(source="level2:push")
                self._update(running=False)

    def _push_toward(self, source_label, destination_label):
        best_gap = float("inf")
        stalled = 0
        last_direction = 0.0
        last_meta = {}
        for cycle in range(1, PUSH_TO_CYCLES + 1):
            if self._stop.is_set():
                return cycle - 1, last_direction, last_meta, "stopped"
            src, dst, meta = detect_pair_samples(
                self.robot, source_label, destination_label, attempts=3, timeout=1.5
            )
            if not src or not dst:
                src, dst, meta = detect_pair_samples(
                    self.robot, source_label, destination_label, attempts=3, timeout=2.0
                )
            if not src or not dst:
                return cycle - 1, last_direction, meta, "source/destination pair lost"

            direction = box_center_x(dst["box"]) - box_center_x(src["box"])
            gap = _box_gap(src["box"], dst["box"])
            overlap = iou(src["box"], dst["box"])
            last_direction, last_meta = direction, meta
            self._update(
                phase="push-to-check",
                push_cycle=cycle,
                destination_offset=round(direction, 3),
                destination_gap=round(gap, 3),
                overlap=round(overlap, 3),
            )
            if overlap >= 0.01 or gap <= PUSH_TO_GAP:
                print(
                    f"[level2] push-to reached destination gap={gap:.3f} "
                    f"overlap={overlap:.3f}",
                    flush=True,
                )
                self._update(phase="done")
                return cycle, direction, meta, ""

            if gap < best_gap - 0.01:
                best_gap, stalled = gap, 0
            else:
                stalled += 1
                if stalled >= 4:
                    return cycle, direction, meta, "push-to is not getting closer"

            blocker = self._blocked(source_label, ignored=(destination_label,))
            if blocker:
                return cycle, direction, meta, f"path blocked by {blocker}"
            steer = 0.0
            if abs(direction) > 0.04:
                steer = math.copysign(min(18.0, max(8.0, abs(direction) * 50)), direction)
            ok, error = self._pulse(
                self._forward_power(), steer, PUSH_TO_PULSE, "push-to"
            )
            if not ok:
                return cycle, direction, meta, error
        return PUSH_TO_CYCLES, last_direction, last_meta, "push-to cycle limit"

    def push_to(self, source, destination):
        with self._run_lock:
            self._stop.clear()
            try:
                source, source_label, source_meta = self._resolve(source)
                destination, destination_label, destination_meta = self._resolve(destination)
            except Exception as exc:
                return {"ok": False, "action": "push_to", "error": str(exc)}
            if source_label in NO_CONTACT:
                return {"ok": False, "action": "push_to", "error": f"contact with {source_label!r} is not allowed"}
            if destination_label in NO_CONTACT:
                return {"ok": False, "action": "push_to", "error": f"pushing toward {destination_label!r} is not allowed"}
            if source_label == destination_label:
                return {"ok": False, "action": "push_to", "error": "source and destination must resolve to different labels"}
            self.current = {
                "running": True, "skill": "push_to", "phase": "acquire",
                "target": source, "destination": destination,
                "label": source_label, "destination_label": destination_label,
                "resolve": {"source": source_meta, "destination": destination_meta},
            }
            print(
                f"[level2] push_to start source={source!r} destination={destination!r}",
                flush=True,
            )
            try:
                det, cycles, _, error = self._approach(
                    source, source_label, contact=True, ignored=(destination_label,)
                )
                if error:
                    return {"ok": False, "action": "push_to", "error": error, "cycles": cycles}
                with self.robot.vision.exclusive():
                    push_cycles, direction, meta, error = self._push_toward(
                        source_label, destination_label
                    )
                return {
                    "ok": not error, "action": "push_to", "source": source,
                    "destination": destination, "cycles": cycles,
                    "push_cycles": push_cycles, "direction": round(direction, 3),
                    "error": error or None, "vision": meta,
                }
            finally:
                self.robot.stop(source="level2:push_to")
                self._update(running=False)
