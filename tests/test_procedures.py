import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from skills import procedures


class FakeMovement:
    def __init__(self):
        self.stops = 0

    def set_velocity(self, *_args, **_kwargs):
        return {"ok": True}

    def stop(self, **_):
        self.stops += 1
        return {"ok": True}

    @staticmethod
    def turn_bounds(default_max=45):
        return 32.0, float(default_max)


class FakeRobot:
    def __init__(self, edge_ready=True, edge_danger=False):
        self.movement = FakeMovement()
        self.edge_ready = edge_ready
        self.edge_danger = edge_danger
        self.power_gauge = type(
            "Gauge",
            (),
            {"status": staticmethod(lambda: {"min_turn": 32.0, "min_forward": 32.0})},
        )()

    def calibrate_power(self):
        return {"ok": True, "breakaway_turn": 30.0, "min_turn": 32.0, "trials": [1, 2]}

    def status(self, force=False):
        return {
            "safety": {
                "edge": {
                    "enabled": True,
                    "ready": self.edge_ready,
                    "danger": self.edge_danger,
                    "reason": "ok" if self.edge_ready and not self.edge_danger else "edge ahead",
                }
            }
        }


class ProcedureTests(unittest.TestCase):
    def test_lists_all_procedures_with_setup_and_steps(self):
        items = procedures.list_procedures()
        ids = [p["id"] for p in items]
        self.assertIn("power_gauge", ids)
        self.assertIn("find_bench", ids)
        self.assertIn("lock_bench", ids)
        self.assertIn("follow_bench", ids)
        self.assertIn("full_suite", ids)
        for p in items:
            self.assertTrue(p["setup"])
            self.assertGreaterEqual(len(p["steps"]), 2)

    def test_power_gauge_procedure_logs_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "procedures.jsonl"
            with patch.object(procedures, "LOG_PATH", log):
                out = procedures.run_procedure(FakeRobot(), "power_gauge", "person")
            self.assertTrue(out["ok"])
            self.assertIn("min 32.0%", out["summary"])
            lines = log.read_text().strip().splitlines()
            self.assertEqual(len(lines), 1)
            self.assertEqual(json.loads(lines[0])["id"], "power_gauge")

    def test_follow_procedure_blocks_when_edge_safety_unready(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "procedures.jsonl"
            with patch.object(procedures, "LOG_PATH", log):
                out = procedures.run_procedure(
                    FakeRobot(edge_ready=False), "follow_bench", "person"
                )
            self.assertFalse(out["ok"])
            self.assertIn("blocked", out["summary"])

    def test_unknown_procedure_returns_error(self):
        out = procedures.run_procedure(FakeRobot(), "does_not_exist")
        self.assertFalse(out["ok"])
        self.assertIn("unknown procedure", out["error"])


if __name__ == "__main__":
    unittest.main()
