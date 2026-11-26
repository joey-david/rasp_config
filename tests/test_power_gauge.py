import json
from pathlib import Path
import tempfile
import threading
import unittest

from skills.power_gauge import PowerGauge
from skills.runtime import timed_velocity


class FakeCamera:
    def __init__(self):
        self.frame_id = 1

    def latest(self):
        return b"jpg", 1.0, self.frame_id


class FakeOdometry:
    def __init__(self, robot, breakaway_power=32.0):
        self.robot = robot
        self.breakaway_power = breakaway_power

    def capture_gray(self, after_frame_id=None, timeout=0.08):
        self.robot.camera.frame_id += 1
        return ("frame", self.robot.last_power), 1.0, self.robot.camera.frame_id, ""

    def measure_shift(self, before, after):
        signed_power = after[1]
        power = abs(signed_power)
        moved = power >= self.breakaway_power
        sign = -1.0 if signed_power > 0 else 1.0
        return {
            "fresh": True,
            "linear_fresh": True,
            "dx": sign * 3.2 if moved else 0.04,
            "dy": 2.6 if moved else 0.03,
            "score": 0.95,
            "linear_score": 0.92,
        }


class FakeMovement:
    def __init__(self, robot):
        self.robot = robot
        self.commands = []

    def set_velocity(self, linear, angular, source=""):
        self.commands.append((linear, angular, source))
        self.robot.last_power = angular if angular else linear
        return {"ok": True}

    def stop(self, **_):
        return {"ok": True}

    def turn_bounds(self, default_max=45):
        return self.robot.power_gauge.turn_bounds(
            default_max=default_max, power_cap=self.robot.motion.power
        )


class FakeRobot:
    def __init__(self, gauge, breakaway_power=32.0):
        self.camera = FakeCamera()
        self.motion = type("Motion", (), {"power": 70.0})()
        self.power_gauge = gauge
        self.last_power = 0.0
        self.odometry = FakeOdometry(self, breakaway_power=breakaway_power)
        self.movement = FakeMovement(self)


class PowerGaugeTests(unittest.TestCase):
    def test_calibrate_ramps_up_to_breakaway_and_persists(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "power_gauge.json"
            gauge = PowerGauge(path=path)
            robot = FakeRobot(gauge, breakaway_power=30.0)

            result = gauge.calibrate(
                robot,
                start_power=18.0,
                step=4.0,
                pulse_seconds=0.05,
                settle_seconds=0.0,
                pre_settle_seconds=0.0,
                margin=2.0,
            )

            self.assertTrue(result["ok"])
            self.assertFalse(result["status"]["running"])
            self.assertEqual(result["breakaway_turn"], 30.0)
            self.assertEqual(result["min_turn"], 32.0)
            self.assertEqual(result["min_forward"], 35.0)
            # Re-loading from disk remembers the calibrated threshold.
            reloaded = PowerGauge(path=path)
            self.assertEqual(reloaded.min_turn, 32.0)
            self.assertEqual(reloaded.status()["source"], "ramp-calibration")

    def test_timed_velocity_triggers_auto_bump_after_three_failed_turns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "power_gauge.json"
            gauge = PowerGauge(path=path, min_turn=26.0, stall_limit=3, bump_step=4.0)
            robot = FakeRobot(gauge, breakaway_power=34.0)
            stop = threading.Event()

            for _ in range(5):
                lo, _ = robot.movement.turn_bounds()
                self.assertFalse(path.exists())
                timed_velocity(robot, stop, 0, lo, 0.09, "test-turn")

            # Three stalls at 26 -> bumps to 30; stall at 30 -> bumps to 34; moves at 34.
            sent = [cmd[1] for cmd in robot.movement.commands]
            self.assertEqual(sent, [26.0, 26.0, 26.0, 30.0, 34.0])
            self.assertEqual(json.loads(path.read_text())["min_turn"], 34.0)
            self.assertEqual(gauge.min_forward, 35.0)
            self.assertEqual(gauge.min_turn, 34.0)
            self.assertEqual(gauge.status()["stall_streak"]["turn"], 0)
            self.assertFalse(gauge.status()["recovering"]["turn"])

    def test_unreliable_stall_samples_do_not_raise_floor(self):
        for power, fresh in [(10.0, True), (35.0, False)]:
            with self.subTest(power=power, fresh=fresh):
                gauge = PowerGauge(path=None, min_turn=35.0)
                for _ in range(gauge.stall_limit + 1):
                    self.assertTrue(gauge.observe_pulse("turn", power, 0.0, fresh)["ignored"])
                self.assertEqual(gauge.min_turn, 35.0)

    def test_same_sign_scene_motion_is_rejected_by_calibrate(self):
        class SceneDriftOdo(FakeOdometry):
            def measure_shift(self, before, after):
                if abs(after[1]) < 30.0:
                    return {"fresh": True, "dx": 2.5, "dy": 0.0, "score": 0.9, "linear_score": 0.9, "linear_fresh": True}
                return super().measure_shift(before, after)

        with tempfile.TemporaryDirectory() as tmp:
            gauge = PowerGauge(path=Path(tmp) / "gauge.json")
            robot = FakeRobot(gauge, breakaway_power=30.0)
            robot.odometry = SceneDriftOdo(robot, breakaway_power=30.0)
            out = gauge.calibrate(
                robot, start_power=18.0, step=4.0, pulse_seconds=0.05,
                settle_seconds=0.0, pre_settle_seconds=0.0, margin=2.0,
            )
            self.assertTrue(out["ok"])
            self.assertEqual(out["breakaway_turn"], 30.0)


if __name__ == "__main__":
    unittest.main()
