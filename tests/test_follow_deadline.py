from contextlib import nullcontext
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from skills import follow


class FollowDeadlineTests(TestCase):
    def run_cycle(self, detect, times):
        robot = SimpleNamespace(movement=Mock(), vision=SimpleNamespace(exclusive=nullcontext))
        with (
            patch.object(follow, "resolve_label", return_value=("person", {})),
            patch.object(follow, "detect_target", side_effect=detect),
            patch.object(follow.time, "monotonic", side_effect=times),
        ):
            follow.follow(robot, cycles=1)
        robot.movement.set_velocity.assert_not_called()
        robot.movement.stop.assert_called()

    def test_late_detection_cannot_advance(self):
        self.run_cycle(lambda *_: ({"box": [.4, .2, .6, .5]}, {}), [0, .6, .6])
        self.assertEqual(follow.status()["error"], "detection deadline exceeded")

    def test_stop_during_inference_discards_reply(self):
        def detect(*_):
            follow.stop_follow()
            return {"box": [.4, .2, .6, .5]}, {}

        self.run_cycle(detect, [0])
