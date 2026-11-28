import importlib.util
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

from hardware.motion import Motion


class MotorSink:
    def __init__(self):
        self.last = (0, 0)

    def drive(self, left, right):
        self.last = left, right

    def status(self):
        return {"claimed": True}

    def close(self):
        pass


class OwnershipTests(unittest.TestCase):
    def test_late_movement_and_cleanup_after_operator_takeover(self):
        spec = importlib.util.spec_from_file_location("isolated_robot", Path(__file__).resolve().parents[1] / "robot_api.py")
        api = importlib.util.module_from_spec(spec)
        sink = MotorSink()
        with patch("hardware.motion.Motion", side_effect=lambda **kw: Motion(sink, **kw)):
            spec.loader.exec_module(api)
        robot = api.robot
        entered, resume = threading.Event(), threading.Event()
        token = robot.owner.claim("follow")
        outcomes = []

        def worker():
            entered.set()
            resume.wait(2)
            outcomes.append(robot.set_velocity(0, 35))
            outcomes.append(robot.stop(source="follow"))

        thread = threading.Thread(target=robot.owner.run, args=(token, worker))
        thread.start()
        try:
            self.assertTrue(entered.wait(1))
            self.assertFalse(robot.set_velocity(0, 40, source="udp")["ok"])
            robot.operator_stop(seq=0)
            self.assertTrue(robot.set_velocity(0, -35, source="udp")["ok"])
            resume.set()
            thread.join(2)
            self.assertEqual([r["ok"] for r in outcomes], [False, False])
            self.assertEqual(sink.last, (-35, 35))
        finally:
            resume.set()
            thread.join(2)
            robot.close()
