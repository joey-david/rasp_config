import contextlib
import os
import threading
import time
import unittest
from unittest.mock import patch

from hardware.ownership import MotionOwner

from autonomy.controller import AutonomyController


class SequencePlanner:
    def __init__(self):
        self.actions = iter([
            {"action": "observe"},
            {"action": "go_to", "target": "bottle"},
            {"action": "stop", "reason": "smoke test complete"},
        ])

    def plan(self, *_):
        return next(self.actions)

    @staticmethod
    def status():
        return {"url": "fake://sequence"}


class BlockingPlanner:
    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()

    def plan(self, *_):
        self.entered.set()
        self.release.wait(1)
        return {"action": "go_to", "target": "bottle"}

    @staticmethod
    def status():
        return {"url": "fake://blocking"}


class FakeCamera:
    pass


class FakeSkills:
    def __init__(self):
        self.stopped = False

    def stop(self):
        self.stopped = True



class FakeRobot:
    def __init__(self):
        self.owner = MotionOwner()
        self.camera = FakeCamera()
        self.vision = type("Vision", (), {"exclusive": lambda _: contextlib.nullcontext()})()
        self.skills = FakeSkills()
        self.calls = []

    def status(self, force=False):
        return {
            "safety": {"edge": {"ready": True, "danger": False, "reason": "ok"}},
            "motion": {"direction": "stopped", "watchdog_alive": 0.01},
            "perception": {"detections": [{
                "label": "bottle", "score": 0.8, "box": [0.4, 0.3, 0.6, 0.7],
                "center": [0.5, 0.5], "relative_depth": 2.5, "quality": 0.8, "age": 0.1,
            }]},
            "map": {"metric": False, "objects": [{"label": "bottle"}]},
        }

    def stop(self, source=""):
        self.calls.append(("stop", source))
        return {"ok": True}

    def goto(self, target):
        self.calls.append(("go_to", target))
        return {"ok": True, "action": "go_to", "cycles": 2}


class CoordinatedAutonomyTests(unittest.TestCase):
    def setUp(self):
        self.capture = patch(
            "autonomy.controller.capture_detect_all",
            return_value=(
                b"same-frame-jpeg",
                [{"label": "bottle"}],
                {"captured_at": time.time(), "frame_id": 7, "infer_ms": 12.0},
            ),
        )
        self.capture.start()
        self.env = patch.dict(os.environ, {"AUTONOMY_SETTLE_SECONDS": "0"})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.capture.stop()

    def test_full_observe_act_stop_loop(self):
        robot = FakeRobot()
        controller = AutonomyController(robot, SequencePlanner())
        result = controller.start("smoke test", max_steps=5)
        self.assertTrue(result["ok"])
        controller._thread.join(timeout=2)
        status = controller.status()
        self.assertFalse(status["running"])
        self.assertEqual(status["phase"], "complete")
        self.assertEqual(len(status["trace"]), 3)
        self.assertIn(("go_to", "bottle"), robot.calls)

    def test_expired_scene_cannot_dispatch_movement(self):
        robot = FakeRobot()
        controller = AutonomyController(robot, SequencePlanner())
        controller.plan_max_age = 0
        controller.start("stale scene", max_steps=3)
        controller._thread.join(timeout=2)
        self.assertNotIn(("go_to", "bottle"), robot.calls)

    def test_stop_discards_in_flight_planner_action(self):
        robot, planner = FakeRobot(), BlockingPlanner()
        controller = AutonomyController(robot, planner)
        controller.start("stop race", max_steps=2)
        self.assertTrue(planner.entered.wait(1))
        controller.stop()
        self.assertTrue(controller.status()["running"])
        self.assertEqual(controller.status()["phase"], "stopping")
        planner.release.set()
        controller._thread.join(timeout=2)
        self.assertNotIn(("go_to", "bottle"), robot.calls)
        self.assertFalse(controller.status()["running"])
        self.assertEqual(controller.status()["phase"], "stopped")


if __name__ == "__main__":
    unittest.main()
