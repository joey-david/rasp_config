import re
import unittest
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class IDs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.controls = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("id"):
            self.ids.append(attrs["id"])
            self.controls[attrs["id"]] = (tag, attrs)


class CockpitContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "web/static/index.html").read_text()
        cls.js = (ROOT / "web/static/cockpit.js").read_text()
        cls.dom = IDs()
        cls.dom.feed(cls.html)

    def test_ids_are_unique_and_javascript_references_exist(self):
        self.assertEqual(len(self.dom.ids), len(set(self.dom.ids)))
        referenced = set(re.findall(r'\$\("([A-Za-z][A-Za-z0-9_-]*)"\)', self.js))
        self.assertEqual(referenced - set(self.dom.ids), set())

    def test_primary_controls_are_native_and_stably_addressable(self):
        for element_id in ("findBtn", "followBtn", "gotoBtn", "pushBtn", "autonomyBtn"):
            tag, attrs = self.dom.controls[element_id]
            self.assertEqual(tag, "button")
            self.assertTrue(attrs.get("onclick") or attrs.get("data-action"))

    def test_text_entry_controls_have_accessible_names(self):
        target_tag, target = self.dom.controls["skillTarget"]
        self.assertEqual(target_tag, "input")
        self.assertTrue(target.get("aria-label"))
        goal_tag, _ = self.dom.controls["autonomyGoal"]
        self.assertEqual(goal_tag, "textarea")


if __name__ == "__main__":
    unittest.main()
