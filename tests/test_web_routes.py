import importlib.util
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FakeSkills:
    def __init__(self):
        self.running = False
        self.stopped = False

    def status(self):
        return {"layer2": {"running": self.running}}

    def stop(self):
        self.stopped = True


class FakeAutonomy:
    def __init__(self):
        self.running = False
        self.stopped = False

    def status(self):
        return {"running": self.running}

    def stop(self):
        self.stopped = True


class FakeRobot:
    def __init__(self):
        self.skills = FakeSkills()
        self.autonomy = FakeAutonomy()
        self.calls = []

    def goto(self, target):
        self.calls.append(("go_to", target))
        return {"ok": True}

    def push_to(self, source, destination):
        self.calls.append(("push_to", source, destination))
        return {"ok": True}

    def calibrate_power(self, **kwargs):
        self.calls.append(("power_gauge", kwargs))
        return {"ok": True, "min_turn": 34.0}


def load_web_interface(robot):
    fake_api = types.ModuleType("robot_api")
    fake_api.robot = robot
    previous = sys.modules.get("robot_api")
    sys.modules["robot_api"] = fake_api
    try:
        spec = importlib.util.spec_from_file_location(
            "web_interface_for_test", ROOT / "web/web_interface.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        if previous is None:
            sys.modules.pop("robot_api", None)
        else:
            sys.modules["robot_api"] = previous


class WebRouteTests(unittest.TestCase):
    def setUp(self):
        self.robot = FakeRobot()
        self.web = load_web_interface(self.robot)

    def test_go_to_and_push_to_dispatch(self):
        self.assertEqual(self.web.handle_skill_post("/skill/go-to", {"target": "cup"})[0], 200)
        self.assertEqual(
            self.web.handle_skill_post(
                "/skill/push-to", {"source": "cup", "destination": "bottle"}
            )[0],
            200,
        )
        self.assertEqual(
            self.robot.calls,
            [("go_to", "cup"), ("push_to", "cup", "bottle")],
        )

    def test_busy_skill_is_rejected(self):
        self.robot.skills.running = True
        code, payload = self.web.handle_skill_post("/skill/go-to", {"target": "cup"})
        self.assertEqual(code, 409)
        self.assertFalse(payload["ok"])

    def test_skill_claim_closes_startup_race(self):
        self.assertTrue(self.web._claim_skill("first"))
        try:
            self.assertTrue(self.web.active_skill())
            self.assertEqual(self.web.claimed_skill(), "first")
            self.assertFalse(self.web._claim_skill("second"))
        finally:
            self.web._release_skill("first")
        self.assertFalse(self.web.active_skill())

    def test_emergency_stop_reaches_all_owned_runners(self):
        code, payload = self.web.handle_skill_post("/skill/stop", {})
        self.assertEqual(code, 200)
        self.assertTrue(payload["stopped"])
        self.assertTrue(self.robot.autonomy.stopped)
        self.assertTrue(self.robot.skills.stopped)

    def test_sync_skill_error_releases_claim(self):
        def fail(_target):
            raise RuntimeError("motor failed")

        self.robot.goto = fail

        code, payload = self.web.handle_skill_post(
            "/skill/go-to", {"target": "bottle"}
        )

        self.assertEqual(code, 500)
        self.assertEqual(payload, {"ok": False, "error": "motor failed"})
        self.assertFalse(self.web.active_skill())

    def test_power_gauge_route_dispatches(self):
        code, payload = self.web.handle_skill_post(
            "/skill/power-gauge", {"start_power": 18, "step": 3}
        )
        self.assertEqual(code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(
            self.robot.calls,
            [("power_gauge", {"start_power": 18, "step": 3})],
        )

    def test_procedure_route_rejects_unknown_id(self):
        code, payload = self.web.handle_skill_post(
            "/skill/procedure", {"id": "bogus"}
        )
        self.assertEqual(code, 400)
        self.assertFalse(payload["ok"])


if __name__ == "__main__":
    unittest.main()
