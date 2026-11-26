import contextlib
import unittest
from unittest.mock import patch

from skills import find


def detection(cx):
    return {
        "label": "person", "score": 0.9,
        "box": [cx - 0.1, 0.2, cx + 0.1, 0.8],
    }


class FakeMovement:
    def __init__(self):
        self.commands = []

    @staticmethod
    def turn(error, *_):
        return 35 if error > 0 else -35

    def set_velocity(self, linear, angular, source=""):
        self.commands.append((linear, angular, source))
        return {"ok": True}

    def stop(self, **_):
        return {"ok": True}


class FakeRobot:
    def __init__(self):
        self.movement = FakeMovement()
        self.vision = type("Vision", (), {"exclusive": lambda _: contextlib.nullcontext()})()


class FindPrecheckTests(unittest.TestCase):
    @patch("skills.find.resolve_label", return_value=("person", {}))
    @patch("skills.find.detect_target", side_effect=TimeoutError("detector offline"))
    def test_outage_does_not_trigger_blind_search(self, _detect, _resolve):
        robot = FakeRobot()
        result = find.find(robot)
        self.assertFalse(result["found"])
        self.assertEqual(result["error"], "detector offline")
        self.assertEqual(robot.movement.commands, [])

    @patch("skills.find.resolve_label", return_value=("person", {"resolve_method": "exact"}))
    @patch("skills.find.detect_target", return_value=(detection(0.5), {"confirmations": 3}))
    def test_centered_precheck_does_not_turn(self, _detect, _resolve):
        robot = FakeRobot()
        result = find.find(robot, "person", max_cycles=1)
        self.assertTrue(result["centered"])
        self.assertTrue(result["precheck_seen"])
        self.assertEqual(robot.movement.commands, [])

    @patch("skills.find.resolve_label", return_value=("person", {"resolve_method": "exact"}))
    @patch("skills.find.timed_velocity")
    @patch("skills.find.detect_target")
    def test_off_center_precheck_uses_bounded_center_pulse(self, detect, pulse, _resolve):
        detect.side_effect = [
            (detection(0.72), {"confirmations": 3}),
            (detection(0.5), {"confirmations": 3}),
        ]
        result = find.find(FakeRobot(), "person", max_cycles=1)
        self.assertTrue(result["centered"])
        pulse.assert_called_once()
        args = pulse.call_args.args
        self.assertEqual(args[2], 0)
        self.assertEqual(args[3], 35)
        self.assertGreaterEqual(args[4], 0.085)
        self.assertLessEqual(args[4], 0.22)

    @patch("skills.find.resolve_label", return_value=("person", {"resolve_method": "exact"}))
    @patch("skills.find.timed_velocity")
    @patch("skills.find._center")
    @patch("skills.find._find_once")
    def test_center_loss_resumes_scan_at_reliable_speed(
        self, find_once, center, pulse, _resolve
    ):
        find_once.side_effect = [
            (detection(0.7), 0.7),
            (detection(0.5), 0.5),
        ]
        center.side_effect = [
            (None, False),
            (detection(0.5), True),
        ]
        result = find.find(FakeRobot(), "person", search_speed=1, max_cycles=1)
        self.assertTrue(result["found"])
        self.assertTrue(result["centered"])
        self.assertEqual(pulse.call_args.args[3], 35)
        self.assertEqual(pulse.call_args.args[5], "find:search")

    @patch("skills.find.resolve_label", return_value=("person", {"resolve_method": "exact"}))
    @patch("skills.find.timed_velocity")
    @patch("skills.find.detect_target")
    def test_miss_clears_stale_box_and_stop_short_circuits_detect(self, detect, pulse, _resolve):
        detect.side_effect = [
            (detection(0.75), {"frame_id": 1}),
            (None, {"frame_id": 2}),
            (None, {"frame_id": 3}),
        ]

        def on_pulse(*args, **_kwargs):
            if args[5] == "find:search":
                find.stop_find()

        pulse.side_effect = on_pulse
        result = find.find(FakeRobot(), "person", max_cycles=2)
        self.assertFalse(result["found"])
        self.assertEqual(result["status"]["phase"], "stopped")
        self.assertIsNone(result["status"]["box"])
        self.assertEqual(result["status"]["error"], "")
        self.assertEqual(detect.call_count, 3)


if __name__ == "__main__":
    unittest.main()
