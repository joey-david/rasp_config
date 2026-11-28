import unittest

from pc_inference.object_detection import ObjectYolo
from pc_inference.resolve_label import LabelResolver


class LabelResolverTests(unittest.TestCase):
    def test_detector_module_imports_without_script_path_hack(self):
        self.assertTrue(callable(ObjectYolo))

    def test_only_resolves_names_and_aliases_supported_by_model(self):
        resolver = LabelResolver(["person", "bottle"])
        self.assertEqual(resolver.resolve("Person"), ("person", "exact", 1.0))
        self.assertEqual(resolver.resolve("human"), ("person", "alias", 1.0))
        for word in ("", "brick", "phone"):
            with self.assertRaises(ValueError):
                resolver.resolve(word)


if __name__ == "__main__":
    unittest.main()
