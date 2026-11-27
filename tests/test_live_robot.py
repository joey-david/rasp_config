"""Opt-in live protocol for the Mac inference stack and physical robot."""

import base64
import json
import os
import statistics
import subprocess
import threading
import time
import unittest
import urllib.request


LIVE = os.getenv("ROBOT_HARDWARE_TESTS") == "1"
MOTION = os.getenv("ROBOT_MOTION_TESTS") == "1"
FAULTS = os.getenv("ROBOT_FAULT_TESTS") == "1"
CONTACT = os.getenv("ROBOT_CONTACT_TESTS") == "1"
PI_URL = os.getenv("ROBOT_URL", "http://192.168.0.43:8080").rstrip("/")
DETECTOR_URL = os.getenv("DETECTOR_URL", "http://127.0.0.1:8081").rstrip("/")
PLANNER_URL = os.getenv("PLANNER_URL", "http://127.0.0.1:8090").rstrip("/")
SSH_HOST = os.getenv("ROBOT_SSH_HOST", "rpi")


def request_json(url, body=None, timeout=10):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        url,
        data=data,
        method="GET" if body is None else "POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


@unittest.skipUnless(LIVE, "set ROBOT_HARDWARE_TESTS=1 for the live protocol")
class LiveRobotProtocol(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.detector = request_json(f"{DETECTOR_URL}/health")
        cls.planner = request_json(f"{PLANNER_URL}/health")
        cls.state = request_json(f"{PI_URL}/api/state")

    def tearDown(self):
        if MOTION:
            request_json(f"{PI_URL}/skill/stop", {})
            request_json(f"{PI_URL}/motion/stop", {})

    def assert_safe(self):
        state = request_json(f"{PI_URL}/api/state")
        edge = state["safety"]["edge"]
        self.assertTrue(edge["enabled"])
        self.assertTrue(edge["ready"], edge)
        self.assertFalse(edge["danger"], edge)
        self.assertLess(state["camera"]["age"], 0.5)
        self.assertEqual(state["camera"]["error"], "")
        self.assertLess(state["motion"]["watchdog_alive"], 0.5)
        return state

    def test_01_preflight(self):
        self.assertTrue(self.detector["ok"])
        self.assertEqual(self.detector["device"], "mps")
        self.assertEqual(self.detector["model"], "yolo11s.pt")
        self.assertTrue(self.planner["ok"])
        self.assertEqual(self.planner["image_max_side"], 320)
        state = self.assert_safe()
        self.assertEqual(state["motion"]["direction"], "stopped")
        self.assertEqual(state["motion"]["backend"]["last"], [0, 0])
        self.assertTrue(state["safety"]["monitoring"])
        self.assertEqual(state["perception"]["error"], "")

    def test_02_same_frame_visual_planner(self):
        with urllib.request.urlopen(f"{PI_URL}/frame/latest.jpg", timeout=5) as response:
            image = response.read()
        body = {
            "goal": "Stop now after checking the scene.",
            "observation": {
                "detections": [],
                "safety": {"edge": {"ready": True, "danger": False}},
                "constraints": {
                    "one_action_per_step": True,
                    "allowed_actions": {"stop": []},
                },
            },
            "image_jpeg": base64.b64encode(image).decode(),
        }
        started = time.monotonic()
        result = request_json(f"{PLANNER_URL}/plan", body, timeout=30)
        self.assertLess(time.monotonic() - started, 8)
        self.assertEqual(result["action"]["action"], "stop")

    @unittest.skipUnless(MOTION, "set ROBOT_MOTION_TESTS=1 for wheel tests")
    def test_03_physical_turn_directions(self):
        self.assert_safe()

        def measure(angular):
            request_json(f"{PI_URL}/api/odometry")
            samples = []
            request_json(
                f"{PI_URL}/motion/set_velocity",
                {"linear": 0, "angular": angular},
            )
            deadline = time.monotonic() + 0.7
            try:
                while time.monotonic() < deadline:
                    sample = request_json(f"{PI_URL}/api/odometry")
                    if sample.get("fresh"):
                        samples.append(sample)
                    time.sleep(0.04)
            finally:
                request_json(f"{PI_URL}/motion/stop", {})
            return samples

        right = measure(35)
        time.sleep(0.3)
        left = measure(-35)
        self.assertGreaterEqual(len(right), 3)
        self.assertGreaterEqual(len(left), 3)
        right_dx = sum(sample["dx"] for sample in right)
        left_dx = sum(sample["dx"] for sample in left)
        self.assertLess(right_dx * left_dx, 0)
        self.assertGreater(abs(right_dx), 1)
        self.assertGreater(abs(left_dx), 1)
        self.assertGreater(statistics.median(x["score"] for x in right), 0.5)
        self.assertGreater(statistics.median(x["score"] for x in left), 0.5)

    @unittest.skipUnless(MOTION, "set ROBOT_MOTION_TESTS=1 for wheel tests")
    def test_04_physical_forward_reverse(self):
        self.assert_safe()

        def measure(linear):
            request_json(f"{PI_URL}/api/odometry")
            samples = []
            request_json(
                f"{PI_URL}/motion/set_velocity",
                {"linear": linear, "angular": 0},
            )
            deadline = time.monotonic() + 0.7
            try:
                while time.monotonic() < deadline:
                    sample = request_json(f"{PI_URL}/api/odometry")
                    if sample.get("linear_fresh"):
                        samples.append(sample)
                    time.sleep(0.04)
            finally:
                request_json(f"{PI_URL}/motion/stop", {})
            return samples

        forward = measure(35)
        time.sleep(0.3)
        reverse = measure(-35)
        self.assertGreaterEqual(len(forward), 3)
        self.assertGreaterEqual(len(reverse), 3)
        forward_dy = sum(sample["dy"] for sample in forward)
        reverse_dy = sum(sample["dy"] for sample in reverse)
        self.assertLess(forward_dy * reverse_dy, 0)
        self.assertGreater(abs(forward_dy), 1)
        self.assertGreater(abs(reverse_dy), 1)

    @unittest.skipUnless(MOTION, "set ROBOT_MOTION_TESTS=1 for emote tests")
    def test_05_emote_moves_both_directions_and_stops(self):
        self.assert_safe()
        result = {}

        def emote():
            result.update(
                request_json(
                    f"{PI_URL}/skill/emote",
                    {"name": "wiggle", "scale": 0.5},
                )
            )

        worker = threading.Thread(target=emote)
        worker.start()
        shifts = []
        while worker.is_alive():
            sample = request_json(f"{PI_URL}/api/odometry")
            if sample.get("fresh") and abs(sample.get("dx", 0)) > 0.05:
                shifts.append(sample["dx"])
            time.sleep(0.035)
        worker.join()
        self.assertTrue(result["ok"])
        self.assertTrue(any(x < 0 for x in shifts))
        self.assertTrue(any(x > 0 for x in shifts))
        self.assertEqual(self.assert_safe()["motion"]["direction"], "stopped")

    @unittest.skipUnless(MOTION, "set ROBOT_MOTION_TESTS=1 for find tests")
    def test_06_find_visible_target(self):
        target = os.getenv("ROBOT_FOLLOW_TARGET")
        if not target:
            self.skipTest("set ROBOT_FOLLOW_TARGET to a visible object")
        self.assert_safe()
        result = request_json(
            f"{PI_URL}/skill/find",
            {"target": target, "max_cycles": 3},
            timeout=60,
        )
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["found"])
        self.assertTrue(result["centered"])
        self.assertEqual(self.assert_safe()["motion"]["direction"], "stopped")

    @unittest.skipUnless(MOTION, "set ROBOT_MOTION_TESTS=1 for follow tests")
    def test_07_follow_has_no_rapid_reversals(self):
        target = os.getenv("ROBOT_FOLLOW_TARGET")
        if not target:
            self.skipTest("set ROBOT_FOLLOW_TARGET to a visible object")
        self.assert_safe()
        request_json(
            f"{PI_URL}/skill/follow",
            {"target": target, "cycles": 16},
        )
        samples = []
        saw_running = False
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            state = self.assert_safe()
            follow = state["skill_runner"]["follow"]
            saw_running |= bool(follow.get("running"))
            if follow.get("seen"):
                sample = (follow.get("cycle"), float(follow.get("turn") or 0))
                if not samples or sample != samples[-1]:
                    samples.append(sample)
            if saw_running and not follow.get("running"):
                break
            time.sleep(0.04)
        turns = [turn for _, turn in samples if turn]
        reversals = sum(a * b < 0 for a, b in zip(turns, turns[1:]))
        self.assertTrue(saw_running)
        self.assertGreaterEqual(len(turns), 2)
        self.assertLessEqual(reversals, 1)

    @unittest.skipUnless(MOTION, "set ROBOT_MOTION_TESTS=1 for approach tests")
    def test_08_go_to_visible_target(self):
        target = os.getenv("ROBOT_GOTO_TARGET")
        if not target:
            self.skipTest("set ROBOT_GOTO_TARGET to a safe visible object")
        self.assert_safe()
        result = request_json(
            f"{PI_URL}/skill/go-to",
            {"target": target},
            timeout=120,
        )
        self.assertTrue(result["ok"], result)
        self.assertLessEqual(result["cycles"], 24)
        self.assertEqual(self.assert_safe()["motion"]["direction"], "stopped")

    @unittest.skipUnless(CONTACT, "set ROBOT_CONTACT_TESTS=1 for contact tests")
    def test_09_push_harmless_target(self):
        target = os.getenv("ROBOT_PUSH_TARGET")
        if not target:
            self.skipTest("set ROBOT_PUSH_TARGET to a safe movable object")
        self.assert_safe()
        result = request_json(
            f"{PI_URL}/skill/push",
            {"target": target},
            timeout=180,
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(self.assert_safe()["motion"]["direction"], "stopped")

    @unittest.skipUnless(FAULTS, "set ROBOT_FAULT_TESTS=1 for fault injection")
    def test_10_stale_camera_blocks_forward(self):
        self.assert_safe()
        pid = subprocess.check_output(
            ["ssh", SSH_HOST, "pgrep -n rpicam-vid"], text=True, timeout=10
        ).strip()
        subprocess.run(["ssh", SSH_HOST, f"kill -STOP {pid}"], check=True, timeout=10)
        try:
            time.sleep(0.8)
            state = request_json(f"{PI_URL}/api/state")
            self.assertEqual(state["safety"]["edge"]["reason"], "stale camera")
            result = request_json(
                f"{PI_URL}/motion/set_velocity",
                {"linear": 35, "angular": 0},
            )
            self.assertFalse(result["ok"])
            self.assertEqual((result["left"], result["right"]), (0, 0))
            self.assertEqual(result["veto"], "stale camera")
        finally:
            subprocess.run(
                ["ssh", SSH_HOST, f"kill -CONT {pid}"], check=False, timeout=10
            )
        time.sleep(1)
        self.assert_safe()

    @unittest.skipUnless(MOTION, "set ROBOT_MOTION_TESTS=1 for autonomy tests")
    def test_11_visual_autonomy_runs_emote_then_stops(self):
        self.assert_safe()
        result = request_json(
            f"{PI_URL}/autonomy/start",
            {"goal": "Perform the wiggle emote once, then stop.", "max_steps": 3},
        )
        self.assertTrue(result["ok"], result)
        saw_running = False
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            state = self.assert_safe()
            autonomy = state["layers"]["level3"]["autonomy"]
            saw_running |= bool(autonomy.get("running"))
            if saw_running and not autonomy.get("running"):
                break
            time.sleep(0.1)
        state = self.assert_safe()
        autonomy = state["layers"]["level3"]["autonomy"]
        actions = [entry["action"]["action"] for entry in autonomy.get("trace", [])]
        self.assertTrue(saw_running)
        self.assertEqual(autonomy.get("error"), "")
        self.assertIn("emote", actions)
        self.assertIn("stop", actions)
        self.assertEqual(state["motion"]["direction"], "stopped")


if __name__ == "__main__":
    unittest.main()
