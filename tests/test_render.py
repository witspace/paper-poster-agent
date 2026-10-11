"""Integration tests exercise the actual browser and independently reopen its PDF."""

import base64
import copy
import json
import tempfile
import unittest
from pathlib import Path

import fitz
from PIL import Image

from poster_agent.project import approve, content_digest, load_spec, reopen, save_revision, write_json
from poster_agent.render import _content_strings, build_html, check_project, export_project


class RenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.project = Path(cls.temporary.name)
        (cls.project / "assets").mkdir()
        Image.new("RGB", (2400, 1200), "#e2f1f2").save(cls.project / "assets/figure.png")
        spec = {
            "schema_version": 1, "version": 1, "status": "draft",
            "conference": {"name": "Fixture Conference", "year": 2026, "track": "Main"},
            "canvas": {"width_mm": 420, "height_mm": 594, "png_width": 6000},
            "title": "A measurable academic poster", "subtitle": "A real browser export with independently verified dimensions.",
            "authors": "Example Researcher", "affiliations": "Example University",
            "layout": {"columns": 2, "margin_mm": 12, "gap_mm": 6, "title_pt": 36, "body_pt": 18},
            "sections": [
                {"id": "question", "heading": "Research question", "kind": "text", "span": 1, "paragraphs": ["Can browser posters preserve exact print size?"], "source_refs": ["paper"]},
                {"id": "findings", "heading": "Findings", "kind": "text", "span": 1, "bullets": ["The exported PDF uses the requested physical dimensions."], "source_refs": ["paper"]},
                {"id": "method", "heading": "Method overview", "kind": "figure", "span": 2, "image": "assets/figure.png", "image_height_mm": 70, "caption": "Original paper asset, preserved in the output.", "source_refs": ["figure"]},
            ],
            "approval": None,
        }
        write_json(cls.project / "poster.json", spec)
        write_json(cls.project / "evidence.json", {"paper": {"title": spec["title"], "sha256": "fixture"}, "items": [{"id": "paper", "page": 1}, {"id": "figure", "page": 2, "source_asset": "assets/figure.png"}], "content_review": {"status": "accepted", "issues": [], "content_sha256": content_digest(spec)}})
        write_json(cls.project / "conference.json", {"sources": [{"url": "https://example.com/fixture", "title": "Local test fixture"}], "requirements": {"width_mm": 420, "height_mm": 594, "orientation": "portrait", "min_ppi": 150}, "unresolved": []})
        cls.initial = copy.deepcopy(spec)
        cls.report = export_project(cls.project)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def setUp(self):
        write_json(self.project / "poster.json", copy.deepcopy(self.initial))

    def test_real_pdf_geometry_fonts_text_and_png_resolution(self):
        self.assertTrue(self.report["technical_pass"], self.report["issues"])
        self.assertTrue(self.report["content_pass"])
        self.assertFalse(self.report["print_ready"], "Export must not approve a design")
        with fitz.open(self.project / "exports/poster-print.pdf") as pdf:
            self.assertEqual(len(pdf), 1)
            self.assertAlmostEqual(pdf[0].rect.width * 25.4 / 72, 420, delta=.001)
            self.assertAlmostEqual(pdf[0].rect.height * 25.4 / 72, 594, delta=.001)
            self.assertIn(self.initial["title"], pdf[0].get_text())
            self.assertTrue(all(pdf.extract_font(font[0])[3] for font in pdf[0].get_fonts()))
        with Image.open(self.project / "exports/poster-4k.png") as png:
            self.assertEqual(png.width, 6000)
            self.assertGreater(png.height, 6000)
        self.assertTrue((self.project / "exports/poster-pdf-preview.png").exists())

    def test_exact_human_approval_then_changed_version_is_stale(self):
        check_project(self.project)
        approve(self.project)
        self.assertTrue(check_project(self.project)["print_ready"])
        reopen(self.project)
        changed = load_spec(self.project)
        changed["layout"]["gap_mm"] = 7
        save_revision(self.project, changed, "Adjust spacing")
        report = check_project(self.project)
        self.assertFalse(report["print_ready"])
        self.assertFalse(report["review"]["human_approval_current"])
        self.assertFalse(next(c for c in report["required_checks"] if c["id"] == "current_export")["passed"])

    def test_html_escapes_text_and_rejects_asset_traversal(self):
        changed = copy.deepcopy(self.initial)
        changed["title"] = '<script>alert("bad")</script>'
        write_json(self.project / "poster.json", changed)
        output = build_html(self.project).read_text(encoding="utf-8")
        self.assertIn("&lt;script&gt;", output)
        self.assertNotIn('<script>alert("bad")</script>', output)
        self.assertIn('data-section-id="method"', output)
        changed["sections"][2]["image"] = "../outside.png"
        write_json(self.project / "poster.json", changed)
        with self.assertRaisesRegex(ValueError, "within project"):
            build_html(self.project)
        write_json(self.project / "poster.json", self.initial)
        build_html(self.project)

    def test_actual_overflow_is_reported(self):
        changed = copy.deepcopy(self.initial)
        changed["sections"][2]["image_height_mm"] = 700
        write_json(self.project / "poster.json", changed)
        report = export_project(self.project, png_width=3840)
        self.assertFalse(next(c for c in report["required_checks"] if c["id"] == "layout_bounds")["passed"])
        self.assertTrue(any(i["section_id"] == "method" and i["severity"] == "error" for i in report["issues"]))
        write_json(self.project / "poster.json", self.initial)
        export_project(self.project)

    def test_narrative_logo_hidden_headings_and_optional_ppi_warning(self):
        Image.new("RGB", (599, 79), "#176b7a").save(self.project / "assets/lab-logo.jpg")
        conference_path = self.project / "conference.json"
        conference = json.loads(conference_path.read_text(encoding="utf-8"))
        optional = copy.deepcopy(conference)
        optional["requirements"]["min_ppi"] = None
        changed = copy.deepcopy(self.initial)
        changed["layout"]["style"] = "narrative"
        changed["branding"] = {"logo": "assets/lab-logo.jpg", "logo_width_mm": 200, "alt": "Local fixture laboratory logo"}
        changed["sections"][0]["heading"] = ""
        changed["sections"][1]["hide_heading"] = True
        write_json(conference_path, optional)
        write_json(self.project / "poster.json", changed)
        try:
            report = export_project(self.project)
            output = (self.project / "exports/poster.html").read_text(encoding="utf-8")
            self.assertIn('class="layout-narrative"', output)
            self.assertNotIn('class="section-number"', output)
            self.assertNotIn('data-content="heading">Findings', output)
            self.assertIn('class="brand-logo"', output)
            self.assertIn('data-asset-role="branding"', output)
            self.assertIn('data-section-id="question"', output)
            logo = next(image for image in report["metrics"]["images"] if image["asset_role"] == "branding")
            self.assertEqual([logo["natural_width"], logo["natural_height"]], [599, 79])
            self.assertAlmostEqual(logo["display_width_mm"], 200, delta=.1)
            self.assertAlmostEqual(logo["effective_ppi"], 76.1, delta=.1)
            self.assertIsNone(logo["minimum_ppi"])
            self.assertFalse(logo["meets_target"])
            self.assertTrue(logo["passed"])
            self.assertTrue(any(issue["severity"] == "warning" and "lab-logo.jpg" in issue["message"] for issue in report["issues"]))
            self.assertTrue(report["technical_pass"], report["issues"])
            self.assertFalse(report["print_ready"], "Aesthetic approval remains an explicit human operation")
            with fitz.open(self.project / "exports/poster-print.pdf") as pdf:
                self.assertEqual(len(pdf), 1)
                self.assertAlmostEqual(pdf[0].rect.width * 25.4 / 72, 420, delta=.001)
                self.assertAlmostEqual(pdf[0].rect.height * 25.4 / 72, 594, delta=.001)
                self.assertNotIn("Findings", pdf[0].get_text())
            with Image.open(self.project / "exports/poster-4k.png") as png:
                self.assertEqual(png.width, 6000)
            # The same measured source becomes a blocker only when an official
            # minimum is actually recorded; no re-render is needed for this rule.
            write_json(conference_path, conference)
            strict = check_project(self.project)
            self.assertFalse(strict["technical_pass"])
            self.assertFalse(next(check for check in strict["required_checks"] if check["id"] == "image_resolution")["passed"])
            self.assertTrue(any(issue["severity"] == "error" and "lab-logo.jpg" in issue["message"] for issue in strict["issues"]))
        finally:
            write_json(conference_path, conference)
            write_json(self.project / "poster.json", self.initial)
            export_project(self.project)

    def test_raster_inside_svg_is_not_treated_as_infinite_resolution(self):
        Image.new("RGB", (40, 20), "#142d44").save(self.project / "assets/tiny.png")
        encoded = base64.b64encode((self.project / "assets/tiny.png").read_bytes()).decode()
        (self.project / "assets/wrapper.svg").write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="800" height="400" viewBox="0 0 800 400"><image href="data:image/png;base64,{encoded}" width="800" height="400"/></svg>', encoding="utf-8")
        changed = copy.deepcopy(self.initial)
        changed["sections"][2]["image"] = "assets/wrapper.svg"
        write_json(self.project / "poster.json", changed)
        report = export_project(self.project, png_width=3840)
        self.assertTrue(report["metrics"]["images"][0]["embedded_raster"])
        self.assertFalse(report["metrics"]["images"][0]["vector"])
        self.assertFalse(next(c for c in report["required_checks"] if c["id"] == "pdf_image_resolution")["passed"])
        self.assertFalse(report["print_ready"])
        write_json(self.project / "poster.json", self.initial)
        export_project(self.project)

    def test_two_tables_share_one_section_and_all_content_is_checked(self):
        changed = copy.deepcopy(self.initial)
        changed["layout"]["style"] = "narrative"
        changed["sections"][0]["rows"] = [["Method", "Error"], ["Demo", 0]]
        changed["sections"][0]["highlight_rows"] = [1]
        changed["sections"][1]["tables"] = [
            {"title": "Synthetic comparison", "rows": [["Method", "Error", "Structure", "Score", "Similarity"], ["Baseline", "2.10", "0.40", "31.00", "0.900"], ["Demo", "1.00", "0.60", "32.00", "0.950"]], "caption": "Fictional values for rendering tests.", "highlight_rows": [2]},
            {"title": "Controlled synthetic comparison", "rows": [["Basis", "Error", "Correlation"], ["Baseline", "3.00", "0.70"], ["Demo", "1.00", "0.90"]], "caption": "Fictional controlled settings.", "highlight_rows": [2]},
        ]
        write_json(self.project / "poster.json", changed)
        try:
            report = export_project(self.project)
            output = (self.project / "exports/poster.html").read_text(encoding="utf-8")
            self.assertEqual(output.count("<table>"), 3)
            self.assertEqual(output.count('class="row-highlight"'), 3)
            self.assertEqual(output.count('data-content="table-title"'), 2)
            self.assertIn('<td data-content="cell">0</td>', output)
            self.assertTrue(report["technical_pass"], report["issues"])
            self.assertEqual(report["metrics"]["pdf_missing_text"], [])
            content = _content_strings(changed)
            for table in changed["sections"][1]["tables"]:
                self.assertIn(table["title"], content)
                self.assertIn(table["caption"], content)
                for row in table["rows"]:
                    for cell in row:
                        self.assertIn(str(cell), content)
            with fitz.open(self.project / "exports/poster-print.pdf") as pdf:
                self.assertEqual(len(pdf), 1)
                self.assertIn("Controlled synthetic comparison", pdf[0].get_text())
                self.assertIn("32.00", pdf[0].get_text())
        finally:
            write_json(self.project / "poster.json", self.initial)
            export_project(self.project)

    def test_changed_original_under_same_path_invalidates_approval(self):
        asset = self.project / "assets/figure.png"
        original = asset.read_bytes()
        try:
            export_project(self.project)
            approve(self.project)
            self.assertTrue(check_project(self.project)["print_ready"])
            Image.new("RGB", (2400, 1200), "#c2d2e2").save(asset)
            export_project(self.project)
            report = check_project(self.project)
            self.assertFalse(report["review"]["human_approval_current"])
            self.assertFalse(report["print_ready"])
        finally:
            asset.write_bytes(original)
            write_json(self.project / "poster.json", self.initial)
            export_project(self.project)


if __name__ == "__main__":
    unittest.main()
