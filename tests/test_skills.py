import contextlib
import unittest
from unittest.mock import patch

from autonomy.controller import AutonomyController
from skills import follow
from skills.objects import ObjectSkills
from skills.tuning import FORWARD_MIN, TURN_MIN


DETECTION = {
    "label": "bottle",
    "score": 0.9,
    "box": [0.35, 0.25, 0.65, 0.75],
    "center": [0.5, 0.5],
    "height": 0.5,
    "relative_depth": 2.0,
}


class FakeMovement:
    @staticmethod
    def turn(error, *_):
        return 35 if error > 0 else -35


class FakeReceiver:
    @staticmethod
    def current():
        return [DETECTION]


class FakeRobot:
    def __init__(self):
        self.movement = FakeMovement()
        self.vision = type("Vision", (), {"exclusive": lambda _: contextlib.nullcontext()})()
        self.perception = type("Perception", (), {"receiver": FakeReceiver()})()
        self.commands = []

    def set_velocity(self, linear, angular, source=""):
        self.commands.append((linear, angular, source))
        return {"ok": True}

    def stop(self, **_):
        return {"ok": True}

    def find(self, *_args, **_kwargs):
        return {"ok": True, "detection": DETECTION}


class ObjectSkillTests(unittest.TestCase):
    @patch("skills.objects.resolve_label", return_value=("bottle", {"resolve_method": "exact"}))
    @patch("skills.objects.detect_target_samples", return_value=(DETECTION, {"confirmations": 3}))
    def test_go_to_stops_when_object_is_already_near(self, _detect, _resolve):
        robot = FakeRobot()
        result = ObjectSkills(robot).go_to("bottle")
        self.assertTrue(result["ok"])
        self.assertEqual(robot.commands, [])

    @patch("skills.objects.resolve_label", return_value=("bottle", {"resolve_method": "exact"}))
    @patch("skills.objects.detect_target_samples", return_value=(None, {}))
    def test_go_to_accepts_find_status_with_overlapping_keys(self, _detect, _resolve):
        robot = FakeRobot()
        status = {"cycle": 4, "seen": True, "box": [0, 0, 0.1, 0.1], "score": 0.2, "offset": 0.4}
        robot.find = lambda *_a, **_k: {"ok": True, "detection": DETECTION, "status": status}
        skills = ObjectSkills(robot)
        result = skills.go_to("bottle")
        self.assertTrue(result["ok"], result)
        self.assertEqual(skills.current["cycle"], 1)
        self.assertEqual(skills.current["box"], DETECTION["box"])

    @patch("skills.objects.resolve_label", return_value=("bottle", {"resolve_method": "exact"}))
    def test_stop_during_detection_skips_search_spin(self, _resolve):
        robot = FakeRobot()
        robot.find = lambda *_a, **_k: self.fail("find() ran after stop")
        skills = ObjectSkills(robot)

        def detect_then_stop(*_a, **_k):
            skills.stop()
            return None, {}

        with patch("skills.objects.detect_target_samples", side_effect=detect_then_stop):
            result = skills.go_to("bottle")
        self.assertFalse(result["ok"])

    @patch("skills.objects.resolve_label", return_value=("person", {}))
    def test_push_rejects_living_target(self, _resolve):
        result = ObjectSkills(FakeRobot()).push("person")
        self.assertFalse(result["ok"])
        self.assertIn("not allowed", result["error"])

    def test_push_to_checks_again_until_source_reaches_destination(self):
        source = {**DETECTION, "box": [0.4, 0.55, 0.6, 0.9]}
        far = {**DETECTION, "label": "cup", "box": [0.7, 0.2, 0.82, 0.4]}
        touching = {**DETECTION, "label": "cup", "box": [0.58, 0.7, 0.75, 0.9]}
        skills = ObjectSkills(FakeRobot())
        with (
            patch(
                "skills.objects.resolve_label",
                side_effect=[("bottle", {}), ("cup", {})],
            ),
            patch.object(
                skills,
                "_approach",
                return_value=(source, 1, {"confirmations": 3}, ""),
            ),
            patch.object(skills, "_blocked", return_value=None),
            patch.object(skills, "_pulse", return_value=(True, "")) as pulse,
            patch(
                "skills.objects.detect_pair_samples",
                side_effect=[
                    (source, far, {"confirmations": 3}),
                    (source, touching, {"confirmations": 3}),
                ],
            ),
        ):
            result = skills.push_to("bottle", "cup")
        self.assertTrue(result["ok"])
        self.assertEqual(result["push_cycles"], 2)
        pulse.assert_called_once()

    @patch(
        "skills.objects.resolve_label",
        side_effect=[("bottle", {}), ("person", {})],
    )
    def test_push_to_rejects_living_destination(self, _resolve):
        result = ObjectSkills(FakeRobot()).push_to("bottle", "person")
        self.assertFalse(result["ok"])
        self.assertIn("toward", result["error"])

    @patch("skills.objects.detect_all", return_value=([], {"error": "expired detection"}))
    def test_expired_frame_does_not_clear_path(self, _detect):
        self.assertEqual(ObjectSkills(FakeRobot())._blocked("bottle"), "vision unavailable")

    @patch("skills.objects.detect_all", side_effect=OSError("camera offline"))
    def test_blocker_check_fails_closed_when_vision_fails(self, _detect):
        skills = ObjectSkills(FakeRobot())

        self.assertEqual(skills._blocked("bottle"), "vision unavailable")
        self.assertEqual(skills.status()["layer2"]["error"], "camera offline")


class PlannerContractTests(unittest.TestCase):
    def test_rejects_raw_motor_action(self):
        with self.assertRaises(ValueError):
            AutonomyController._validate({"action": "set_velocity", "linear": 100})

    def test_clamps_wait(self):
        self.assertEqual(
            AutonomyController._validate({"action": "wait", "seconds": 999})["seconds"],
            5.0,
        )

    def test_rejects_overlong_target(self):
        with self.assertRaises(ValueError):
            AutonomyController._validate({"action": "find", "target": "x" * 81})


class SharedTuningTests(unittest.TestCase):
    @patch("skills.follow.resolve_label", return_value=("person", {"resolve_method": "exact"}))
    @patch("skills.follow.timed_velocity")
    @patch("skills.follow.detect_target")
    def test_follow_separates_turn_and_forward_and_reports_veto(
        self, detect, pulse, _resolve
    ):
        class TurnRampMovement:
            def __init__(self):
                self.stops = 0
                self.velocities = []
                self.veto_next = False

            @staticmethod
            def turn(error, *_):
                return 9.8 if error > 0 else -9.8 if error < 0 else 0.0

            def set_velocity(self, linear, angular, source=""):
                self.velocities.append((linear, angular, source))
                if self.veto_next:
                    return {"ok": False, "veto": "edge ahead"}
                return {"ok": True}

            def stop(self, **_):
                self.stops += 1
                return {"ok": True}

        robot = FakeRobot()
        robot.movement = TurnRampMovement()
        far_off_center = {"label": "person", "score": 0.9, "box": [0.70, 0.2, 0.90, 0.5]}
        slight_off_far = {"label": "person", "score": 0.9, "box": [0.48, 0.2, 0.68, 0.5]}
        centered_near = {"label": "person", "score": 0.9, "box": [0.35, 0.1, 0.65, 0.85]}
        centered_far = {"label": "person", "score": 0.9, "box": [0.40, 0.2, 0.60, 0.5]}

        detect.side_effect = [
            (far_off_center, {"frame_id": 1}),
            (slight_off_far, {"frame_id": 2}),
            (centered_near, {"frame_id": 3}),
            (centered_far, {"frame_id": 4}),
            OSError("detector timeout"),
        ]
        pulse.return_value = {"ok": True}

        # Run 3 cycles first (pivot, floor-safe curve forward, hold), then 1 vetoed forward cycle.
        follow.follow(robot, "person", hz=100, cycles=3)
        self.assertEqual(pulse.call_count, 1)
        # 1) Far off-center (> 0.22): pivot in place at >= TURN_MIN, zero linear.
        self.assertEqual(pulse.call_args_list[0].args[2], 0.0)
        self.assertGreaterEqual(abs(pulse.call_args_list[0].args[3]), TURN_MIN)
        # 2) Slight offset (0.08): smooth forward curve keeping inner wheel >= FORWARD_MIN.
        self.assertEqual(len(robot.movement.velocities), 1)
        lin, ang, _ = robot.movement.velocities[0]
        self.assertGreater(ang, 0.0)
        self.assertGreaterEqual(lin - abs(ang), FORWARD_MIN)

        # 4) Vetoed forward reports blocked with zero linear/turn.
        robot.movement.veto_next = True
        follow.follow(robot, "person", hz=100, cycles=1)
        status = follow.status()
        self.assertEqual(status["phase"], "blocked")
        self.assertEqual(status["veto"], "edge ahead")
        self.assertEqual(status["linear"], 0.0)
        self.assertEqual(status["turn"], 0.0)

        # 5) Detection error clears veto and box and reports search phase cleanly.
        follow.follow(robot, "person", hz=100, cycles=1)
        status = follow.status()
        self.assertEqual(status["phase"], "search")
        self.assertEqual(status["veto"], "")
        self.assertEqual(status["error"], "detector timeout")
        self.assertIsNone(status["box"])


if __name__ == "__main__":
    unittest.main()
