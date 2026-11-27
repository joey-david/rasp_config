import unittest
from unittest.mock import patch

from pc_inference.object_detection import ObjectYolo
from pc_inference.resolve_label import LabelResolver


class LabelResolverTests(unittest.TestCase):
    def test_detector_module_imports_without_script_path_hack(self):
        self.assertTrue(callable(ObjectYolo))

    def test_exact_resolution_does_not_load_embeddings(self):
        resolver = LabelResolver(["person", "bottle"])
        with patch.object(resolver, "_semantic") as semantic:
            self.assertEqual(resolver.resolve("Person"), ("person", "exact", 1.0))
            semantic.assert_not_called()

    def test_semantic_resolution_is_cached(self):
        resolver = LabelResolver(["person", "bottle"])
        with patch.object(
            resolver, "_semantic", return_value=("person", "mlx-embedding", 0.9)
        ) as semantic:
            self.assertEqual(resolver.resolve("human")[0], "person")
            self.assertEqual(resolver.resolve("human")[0], "person")
            semantic.assert_called_once_with("human")


if __name__ == "__main__":
    unittest.main()
