"""Original import and crop tests exercise the actual PDF/vector boundaries."""
import base64
import io
from pathlib import Path
import tempfile
import unittest

import fitz
from PIL import Image

from poster_agent.ingest import extract_regions, ingest, validate_svg
from poster_agent.project import read_json


class IngestTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.project = self.root / "project"
        self.paper = self.root / "paper.pdf"
        with fitz.open() as document:
            for index in range(2):
                page = document.new_page(width=300, height=400)
                page.insert_text((30, 40), f"Paper page {index + 1}")
                page.draw_rect(fitz.Rect(40, 90, 250, 200), color=(.1, .5, .6), width=3)
            document.save(self.paper)

    def tearDown(self):
        self.temporary.cleanup()

    def test_existing_conference_without_paper_is_not_overwritten(self):
        self.project.mkdir()
        conference = self.project / "conference.json"
        conference.write_bytes(b'{"identity":{"name":"Existing project"},"private_note":"keep"}')
        before = conference.read_bytes()
        with self.assertRaisesRegex(ValueError, "managed inputs"):
            ingest(self.project, self.paper, {"name": "Replacement"})
        self.assertEqual(conference.read_bytes(), before)
        self.assertFalse((self.project / "source/paper.pdf").exists())

    def test_original_types_nested_paths_and_vectors_are_preserved(self):
        originals = self.root / "originals"
        (originals / "nested").mkdir(parents=True)
        vector = originals / "nested/plot.pdf"
        vector.write_bytes(self.paper.read_bytes())
        svg = originals / "overview.svg"
        svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="300" height="150"><path d="M20 20 L250 120" stroke="#176b7a" stroke-width="5"/></svg>', encoding="utf-8")
        Image.new("RGB", (800, 400), "#176b7a").save(originals / "photo.jpg")
        Image.new("RGB", (120, 60), "#ffffff").save(originals / "tiny.png")
        (originals / "ignored.tex").write_text("Ignored unrequested source code.")
        result = ingest(self.project, self.paper, {"name": "Fixture"}, assets_dir=originals)
        self.assertEqual(result["pages"], 2)
        self.assertEqual(result["assets"], 5)
        catalog = read_json(self.project / "assets/catalog.json")["entries"]
        self.assertEqual({entry["type"] for entry in catalog}, {"pdf", "svg", "jpg", "png"})
        for entry in catalog:
            self.assertTrue((self.project / entry["path"]).exists())
            self.assertTrue((self.project / entry["preview"]).exists())
            original = originals / entry["original_relative_path"]
            self.assertEqual((self.project / entry["source_file"]).read_bytes(), original.read_bytes())
        imported_pdf = [entry for entry in catalog if entry["type"] == "pdf"]
        self.assertEqual([entry["page"] for entry in imported_pdf], [1, 2])
        for entry in imported_pdf:
            markup = (self.project / entry["path"]).read_text(encoding="utf-8")
            self.assertIn("<path", markup)
            self.assertNotIn("<image", markup, "A vector-only PDF must not be flattened")
        tiny = next(entry for entry in catalog if entry["type"] == "png")
        self.assertEqual(tiny["native_pixels"], [120, 60])
        with Image.open(self.project / tiny["preview"]) as preview:
            self.assertEqual(preview.size, (120, 60), "Preview must not fabricate detail by enlarging native pixels")
        self.assertFalse((self.project / "source/original-assets/ignored.tex").exists())
        source_before = (self.project / "source/paper.pdf").read_bytes()
        with self.assertRaisesRegex(ValueError, "already contains"):
            ingest(self.project, self.paper, {"name": "Other"})
        self.assertEqual((self.project / "source/paper.pdf").read_bytes(), source_before)

    def test_multiple_crop_calls_merge_provenance_and_refuse_duplicate_ids(self):
        ingest(self.project, self.paper, {"name": "Fixture"})
        first = {"id": "figure-one", "page": 1, "bbox": [.05, .05, .95, .7]}
        second = {"id": "figure-two", "page": 2, "bbox": [.05, .05, .95, .7]}
        extract_regions(self.project, [first])
        original_bytes = (self.project / "assets/figure-one.svg").read_bytes()
        extract_regions(self.project, [second])
        self.assertEqual([entry["id"] for entry in read_json(self.project / "assets/provenance.json")], ["figure-one", "figure-two"])
        self.assertEqual([entry["id"] for entry in read_json(self.project / "assets/catalog.json")["entries"]], ["figure-one", "figure-two"])
        with self.assertRaisesRegex(ValueError, "already exists"):
            extract_regions(self.project, [first])
        self.assertEqual((self.project / "assets/figure-one.svg").read_bytes(), original_bytes)
        self.assertIn(b"<path", original_bytes)
        self.assertNotIn(b"<image", original_bytes)

    def test_invalid_crop_batch_does_not_write_first_valid_region(self):
        ingest(self.project, self.paper, {"name": "Fixture"})
        valid = {"id": "valid", "page": 1, "bbox": [0, 0, 1, 1]}
        for invalid in (
            {"id": "bad", "page": 0, "bbox": [0, 0, 1, 1]},
            {"id": "bad", "page": 3, "bbox": [0, 0, 1, 1]},
            {"id": "bad", "page": 1.5, "bbox": [0, 0, 1, 1]},
            {"id": "bad", "page": 1, "bbox": [0, 0, 1.01, 1]},
            {"id": "bad", "page": 1, "bbox": [0, 0, float("nan"), 1]},
            {"id": "../escape", "page": 1, "bbox": [0, 0, 1, 1]},
        ):
            with self.assertRaises(ValueError):
                extract_regions(self.project, [valid, invalid])
            self.assertFalse((self.project / "assets/valid.svg").exists())

    def test_svg_scripts_external_resources_and_output_recursion_are_rejected(self):
        originals = self.root / "originals"
        originals.mkdir()
        svg = originals / "unsafe.svg"
        for content in (
            '<script>alert(1)</script>',
            '<rect onload="alert(1)"/>',
            '<image href="https://example.invalid/figure.png"/>',
            '<image href="local.png"/>',
            '<style>@import "https://example.invalid/a.css";</style>',
            '<rect fill="url(https://example.invalid/paint.svg)"/>',
            '<style>rect { fill: u\\72l(https://example.invalid/paint.svg); }</style>',
            '<image xml:base="https://example.invalid/" href="#other"/>',
            '<foreignObject><p>HTML</p></foreignObject>',
        ):
            svg.write_text(f'<svg xmlns="http://www.w3.org/2000/svg">{content}</svg>', encoding="utf-8")
            with self.assertRaises(ValueError):
                ingest(self.project, self.paper, {"name": "Fixture"}, originals)
            self.assertFalse((self.project / "source/paper.pdf").exists())
        buffer = io.BytesIO()
        Image.new("RGB", (10, 10), "white").save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode()
        svg.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><image href="data:image/png;base64,{encoded}" width="10" height="10"/></svg>')
        validate_svg(svg)
        with self.assertRaisesRegex(ValueError, "outside"):
            ingest(originals / "output", self.paper, {"name": "Fixture"}, originals)


if __name__ == "__main__":
    unittest.main()
