import threading
import time
import unittest
from unittest.mock import patch

import numpy as np

from hardware.safety.danger import EdgeDetector
from mischief_common.nms import nms
from perception.receiver import DetectionReceiver
from perception.odometry.angular import AngularSpeedEstimator
from perception.odometry.linear import LinearSpeedEstimator
from perception.spatial_map import SpatialMap
from perception.vision import capture_detect_all


class DetectionContractTests(unittest.TestCase):
    def test_receiver_adds_geometry_and_dynamic_age(self):
        receiver = DetectionReceiver()
        now = time.time()
        receiver.ingest({
            "captured_at": now,
            "detections": [{"label": "bottle", "score": 0.8, "box": [0.2, 0.3, 0.4, 0.9]}],
        })
        detection = receiver.current(now + 0.2)[0]
        self.assertAlmostEqual(detection["center"][0], 0.3)
        self.assertAlmostEqual(detection["center"][1], 0.6)
        self.assertAlmostEqual(detection["height"], 0.6)
        self.assertAlmostEqual(detection["relative_depth"], 1 / 0.6)
        self.assertAlmostEqual(detection["age"], 0.2, places=2)
        self.assertGreater(detection["quality"], 0.6)

    def test_same_label_overlap_is_deduplicated(self):
        detections = [
            {"label": "car", "score": 0.8, "box": [0.1, 0.1, 0.5, 0.5]},
            {"label": "car", "score": 0.6, "box": [0.11, 0.11, 0.49, 0.49]},
            {"label": "person", "score": 0.7, "box": [0.1, 0.1, 0.5, 0.5]},
        ]
        self.assertEqual([d["label"] for d in nms(detections)], ["car", "person"])


class EdgeDetectorTests(unittest.TestCase):
    def test_repeated_poll_of_one_frame_does_not_warm_up(self):
        safe = np.random.default_rng(2).integers(0, 255, (240, 320), dtype=np.uint8)
        detector = EdgeDetector(warmup_frames=3)
        frame_at = time.time()
        for _ in range(8):
            status = detector.check(safe, frame_at=frame_at, learn=True)
        self.assertFalse(status["ready"])
        self.assertEqual(status["samples"], 1)

    def test_texture_drop_is_confirmed_as_edge(self):
        rng = np.random.default_rng(4)
        safe = rng.integers(0, 255, (240, 320), dtype=np.uint8)
        detector = EdgeDetector(warmup_frames=4, confirm_frames=2)
        for _ in range(5):
            status = detector.check(safe, time.time(), learn=True)
        self.assertTrue(status["ready"])
        self.assertFalse(status["danger"])

        edge = safe.copy()
        edge[170:235, 58:262] = 127
        detector.check(edge, time.time(), learn=False)
        status = detector.check(edge, time.time(), learn=False)
        self.assertTrue(status["danger"])

        samples = status["samples"]
        for _ in range(3):
            status = detector.check(safe, time.time(), learn=True)
            self.assertTrue(status["danger"])
            self.assertEqual(status["samples"], samples)
        status = detector.check(safe, time.time(), learn=True)
        self.assertFalse(status["danger"])

    def test_stale_camera_fails_closed(self):
        detector = EdgeDetector(stale_seconds=0.1)
        status = detector.check(np.zeros((240, 320), np.uint8), time.time() - 1)
        self.assertTrue(status["danger"])
        self.assertEqual(status["reason"], "stale camera")

    def test_dark_object_above_textured_table_is_not_false_edge(self):
        rng = np.random.default_rng(11)
        table = rng.integers(120, 175, (240, 320), dtype=np.uint8)
        detector = EdgeDetector(warmup_frames=4, confirm_frames=2)
        for _ in range(5):
            status = detector.check(table, time.time(), learn=True)
        self.assertTrue(status["ready"])
        self.assertFalse(status["danger"])

        # High-contrast object above y=0.80 with intact wood-grain table below it.
        scene = table.copy()
        scene[120:192, 40:280] = rng.integers(0, 255, (72, 240), dtype=np.uint8)
        for _ in range(3):
            status = detector.check(scene, time.time(), learn=False)
        self.assertFalse(status["danger"])


class SafetyMonitorTests(unittest.TestCase):
    def tearDown(self):
        from hardware.safety import safety
        safety.stop()
        if safety._thread:
            safety._thread.join(1)
        safety._thread = None
        safety.reset()

    @staticmethod
    def _robot(camera):
        motion = type("Motion", (), {"left": 0, "right": 0, "linear": 0, "stop": lambda self: None})()
        return type("Robot", (), {"motion": motion, "camera": camera, "control": {}})()

    def test_monitor_survives_a_failing_tick(self):
        from hardware.safety import safety

        class FlakyCamera:
            calls = 0

            @property
            def gray(self):
                FlakyCamera.calls += 1
                if FlakyCamera.calls == 1:
                    raise RuntimeError("transient")
                return None

            gray_at = None

        safety.start(self._robot(FlakyCamera()))
        deadline = time.time() + 2
        while FlakyCamera.calls < 3 and time.time() < deadline:
            time.sleep(0.02)
        self.assertGreaterEqual(FlakyCamera.calls, 3)
        self.assertTrue(safety.status()["monitoring"])

    def test_forward_is_vetoed_when_monitor_thread_died(self):
        from hardware.safety import safety

        dead = threading.Thread(target=lambda: None)
        dead.start()
        dead.join()
        safety._stop.clear()
        safety._thread = dead
        robot = self._robot(type("Camera", (), {"gray": None, "gray_at": None})())
        self.assertFalse(safety.command_allowed(robot, 30))
        self.assertEqual(safety.status()["last_veto"], "safety monitor stopped")
        self.assertTrue(safety.command_allowed(robot, -30))

    def test_baseline_not_learned_while_a_skill_is_active(self):
        from hardware.safety import safety

        robot = self._robot(type("Camera", (), {"gray": None, "gray_at": None})())
        robot.skill_active = lambda: True
        safety._moving_at = 0.0
        self.assertFalse(safety._idle_for_learning(robot))
        robot.skill_active = lambda: False
        self.assertFalse(safety._idle_for_learning(robot))
        safety._moving_at -= safety.LEARN_IDLE_SECONDS
        self.assertTrue(safety._idle_for_learning(robot))


class SpatialMapTests(unittest.TestCase):
    def test_map_reports_relative_pose_and_landmark(self):
        world = SpatialMap()
        world.command(0, 35, now=0)
        world.command(0, 0, now=0.25)
        world.observe([{
            "label": "bottle", "center": [0.5, 0.5],
            "relative_depth": 2.0, "score": 0.8,
        }], now=0.25)
        status = world.status()
        self.assertFalse(status["metric"])
        self.assertNotEqual(status["pose"]["yaw"], 0)
        self.assertEqual(status["objects"][0]["label"], "bottle")

    def test_landmark_uses_pose_when_frame_was_captured(self):
        world = SpatialMap()
        world.command(100, 0, now=100.0)
        world.command(0, 0, now=101.0)
        world.observe([{
            "label": "bottle", "center": [0.5, 0.5],
            "relative_depth": 2.0, "score": 0.8,
        }], now=101.0, observed_at=100.25)
        bottle = world.status()["objects"][0]
        self.assertAlmostEqual(bottle["z"], 2.25, places=2)


class VisualOdometryTests(unittest.TestCase):
    def test_estimators_recover_known_image_shift(self):
        frame = np.random.default_rng(7).normal(size=(120, 160)).astype(np.float32)
        shifted = np.roll(np.roll(frame, 4, axis=1), 3, axis=0)
        angular = AngularSpeedEstimator(fx_px=80, roi=(0, 1))
        linear = LinearSpeedEstimator(roi=(0, 1))
        self.assertIsNone(angular.update(frame, 1.0))
        self.assertIsNone(linear.update(frame, 1.0))
        turn = angular.update(shifted, 2.0)
        drive = linear.update(shifted, 2.0)
        self.assertAlmostEqual(turn["dx"], 4, delta=0.1)
        self.assertAlmostEqual(drive["dy"], 3, delta=0.1)
        self.assertGreater(turn["score"], 0.9)
        self.assertGreater(drive["score"], 0.9)


class CoordinatedVisionTests(unittest.TestCase):
    def test_detection_and_planner_share_one_captured_frame(self):
        class Camera:
            @staticmethod
            def latest():
                return b"old", 9.0, 4

            @staticmethod
            def snapshot_with_meta(timeout, after_frame_id):
                self.assertEqual(after_frame_id, 4)
                return b"new-jpeg", 10.0, 5

        class Robot:
            camera = Camera()

            def __init__(self):
                self.payload = None

            def ingest_detections(self, payload):
                self.payload = payload

        robot = Robot()
        reply = {
            "model": "fake",
            "detections": [{"label": "bottle", "box": [0.4, 0.3, 0.6, 0.8]}],
            "infer_ms": 4.0,
        }
        timing = (10.0, 5, 10.1, 10.2)
        with patch(
            "perception.vision._post_jpeg",
            return_value=(reply, timing, {}),
        ) as post:
            frame, detections, meta = capture_detect_all(robot)
        self.assertEqual(frame, b"new-jpeg")
        self.assertEqual(post.call_args.args[3], frame)
        self.assertEqual(detections[0]["label"], "bottle")
        self.assertEqual(meta["frame_id"], 5)
        self.assertEqual(robot.payload["frame_id"], 5)


if __name__ == "__main__":
    unittest.main()
