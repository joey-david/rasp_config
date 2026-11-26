import unittest

from skills.runtime import VisualTurnController


class TargetCrossingTests(unittest.TestCase):
    def test_crossing_suppresses_old_turn_until_reversal_confirmed(self):
        for side in (-1, 1):
            with self.subTest(side=side):
                steering = VisualTurnController(0.01)
                allowed = [steering.update(side * x)[1] for x in (0.14, -0.08, -0.08, -0.08)]
                self.assertEqual(allowed, [True, False, False, True])

    def test_centered_observation_blocks_residual_turn(self):
        steering = VisualTurnController(0.01)
        steering.update(0.3)
        offset, allowed = steering.update(0.005)
        self.assertGreater(offset, 0.01)
        self.assertFalse(allowed)
