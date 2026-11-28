import importlib.util
from pathlib import Path
import sys
import unittest
import time
from unittest.mock import Mock, patch

from hardware.motion import Motion


class FakeMotors:
    def __init__(self):
        self.last = (0, 0)
        self.closed = False

    def drive(self, left, right):
        self.last = (left, right)

    def close(self):
        self.closed = True

    def status(self):
        return {"backend": "fake", "last": self.last, "claimed": not self.closed}


class MotionTests(unittest.TestCase):
    @patch("hardware.motion.WATCHDOG_SECONDS", 0.05)
    def test_watchdog_stops_a_stale_command(self):
        backend = FakeMotors()
        motion = Motion(backend)
        try:
            motion.set_velocity(35, 0)
            time.sleep(0.25)
            self.assertEqual(backend.last, (0.0, 0.0))
            self.assertEqual(motion.direction, "stopped")
        finally:
            motion.close()

    def test_observer_receives_actual_commands_and_stop(self):
        seen = []
        motion = Motion(FakeMotors(), observer=lambda linear, angular: seen.append((linear, angular)))
        try:
            motion.set_velocity(35, 10)
            motion.stop()
            self.assertEqual(motion.backend.last, (0, 0))
            self.assertEqual(seen[:2], [(35.0, 10.0), (0.0, 0.0)])
        finally:
            motion.close()

    def test_partial_write_disables_driver_until_restart(self):
        spec = importlib.util.spec_from_file_location("test_gpio_backend", Path(__file__).resolve().parents[1] / "hardware/motors.py")
        module = importlib.util.module_from_spec(spec)
        gpio = Mock()
        with patch.dict(sys.modules, {"lgpio": gpio}):
            spec.loader.exec_module(module)
        for fail_at in (1, 2):
            driver = module.Motors()
            driver.drive(20, 20)
            gpio.tx_pwm.side_effect = [None] * (fail_at - 1) + [OSError("PWM failure")]
            with self.assertRaises(OSError):
                driver.drive(35, 35)
            gpio.gpio_write.assert_called_with(driver.handle, driver.cfg["standby"], 0)
            gpio.tx_pwm.side_effect = None
            driver.stop()
            with self.assertRaises(RuntimeError):
                driver.drive(20, 20)
            driver.close()

    def test_nonfinite_command_never_reaches_wheels(self):
        backend = FakeMotors()
        motion = Motion(backend)
        try:
            for value in (float("nan"), float("inf"), -float("inf")):
                with self.assertRaises(ValueError):
                    motion.tank(10, value)
                self.assertEqual(backend.last, (0, 0))
        finally:
            motion.close()

    def test_power_cap_scales_both_wheels_to_keep_steering(self):
        backend = FakeMotors()
        motion = Motion(backend, power_cap=50)
        try:
            status = motion.set_velocity(80, 40)
            self.assertEqual(backend.last, (50.0, 16.7))
            self.assertEqual(status["power"], 50.0)
            self.assertAlmostEqual(status["linear"], 33.35)
        finally:
            motion.close()


if __name__ == "__main__":
    unittest.main()
