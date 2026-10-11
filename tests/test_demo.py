"""The public offline demo proves an end-to-end printable export without model calls."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import fitz
from PIL import Image

from poster_agent.demo import create_demo
from poster_agent.project import read_json


class DemoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.project = Path(cls.temporary.name) / "demo"
        with patch("openai.OpenAI", side_effect=AssertionError("Offline demo must not instantiate an API client")):
            cls.result = create_demo(cls.project)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_synthetic_disclosure_sources_and_no_conference_claim(self):
        spec = read_json(self.project / "poster.json")
        conference = read_json(self.project / "conference.json")
        evidence = read_json(self.project / "evidence.json")
        self.assertTrue(conference["is_demo"])
        self.assertEqual(conference["identity"]["name"], "Demonstration")
        self.assertEqual(conference["sources"], [])
        self.assertIn("SYNTHETIC DATA", spec["affiliations"])
        self.assertTrue(all(section["source_refs"] for section in spec["sections"]))
        known = {item["id"] for item in evidence["items"]}
        self.assertTrue(all(ref in known for section in spec["sections"] for ref in section["source_refs"]))
        self.assertEqual(evidence["content_review"]["status"], "accepted")
        source_text = (self.project / "source/paper.txt").read_text(encoding="utf-8")
        self.assertIn("No participants were recruited", source_text)
        self.assertIn("14.0", source_text)
        self.assertIn("9.5", source_text)
        self.assertIn("6.0", source_text)

    def test_real_single_page_a0_export_and_vector_detail(self):
        with fitz.open(self.project / "exports/poster-print.pdf") as document:
            self.assertEqual(len(document), 1)
            self.assertAlmostEqual(document[0].rect.width * 25.4 / 72, 841, delta=.001)
            self.assertAlmostEqual(document[0].rect.height * 25.4 / 72, 1189, delta=.001)
            self.assertIn("SYNTHETIC DATA", document[0].get_text())
            self.assertEqual(document[0].get_images(), [], "The three original vector figures must remain vectors")
        with Image.open(self.project / "exports/poster-4k.png") as image:
            self.assertEqual(image.size, (6000, round(6000 * 1189 / 841)))
        report = self.result["quality"]
        self.assertFalse(report["print_ready"], "Demo export must not certify a real conference poster")
        relevant = {check["id"]: check for check in report["required_checks"]}
        for name in ("layout_bounds", "pdf_geometry", "pdf_content", "font_embedding", "source_evidence", "html_pdf_consistency"):
            self.assertTrue(relevant[name]["passed"], relevant[name])

    def test_existing_demo_never_gets_overwritten(self):
        before = (self.project / "poster.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "empty"):
            create_demo(self.project)
        self.assertEqual(before, (self.project / "poster.json").read_bytes())


if __name__ == "__main__":
    unittest.main()
