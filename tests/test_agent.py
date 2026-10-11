"""API contracts and evidence safeguards without live API requests or fees."""
import base64
import copy
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import fitz
from PIL import Image

from poster_agent import agent
from poster_agent.ingest import ingest
from poster_agent.project import (content_digest, load_spec, read_json, spec_digest,
                                  write_json)
from poster_agent.render import export_project


def draft_fixture(image=None):
    spec = {"title": "Evidence-preserving academic posters", "subtitle": "A local test fixture",
            "authors": "Example Researcher", "affiliations": "Example Laboratory",
            "theme": {"accent": "#176b7a", "secondary": "#e39b4c", "ink": "#152c3d", "background": "#ffffff", "font": "Arial"},
            "layout": {"columns": 2, "margin_mm": 12, "gap_mm": 6, "title_pt": 36, "body_pt": 18},
            "sections": [{"id": "method", "heading": "A connected method", "kind": "figure" if image else "text", "span": 2,
                          "paragraphs": ["The study reports a controlled comparison."], "source_refs": ["paper"]}],
            "reference_image": "reference/design-reference.png"}
    if image:
        spec["sections"][0].update(image=image, image_height_mm=60, caption="Original diagram from the supplied paper.")
    return {"poster": spec, "evidence": {"paper": {"title": spec["title"]}, "items": [{"id": "paper", "page": 1, "text": "A controlled comparison"}]},
            "original_assets": [], "figure_regions": []}


def accepted_critique():
    return {"content": {"status": "accepted", "issues": []}, "style": {"issues": []},
            "aesthetics": {"issues": []}, "print_visual": {"issues": []}, "summary": "Paper facts match; inspect actual print scale."}


def initialize_fixture(directory):
    paper = directory / "fixture-paper.pdf"
    with fitz.open() as document:
        page = document.new_page(width=420, height=594)
        page.insert_text((30, 35), "Evidence-preserving academic posters")
        page.insert_text((30, 55), "The study reports a controlled comparison.")
        page.draw_rect(fitz.Rect(35, 90, 320, 180), color=(.1, .4, .5), fill=(.9, .95, .96))
        page.insert_text((60, 130), "Input -> verified method -> controlled result")
        document.save(paper)
    project = directory / "project"
    identity = {"name": "Fixture Conference", "year": 2026, "track": "Main"}
    ingest(project, paper, identity)
    conference = {"identity": identity, "checked_at": "2026-10-08T00:00:00Z", "sources": [{"url": "https://example.org/posters", "quote": "420 x 594 mm portrait", "verification": "explicitly_imported_checked_profile"}],
                  "requirements": {"width_mm": 420, "height_mm": 594, "orientation": "portrait", "min_ppi": None}, "unresolved": []}
    write_json(project / "conference.json", conference)
    return project


def image_response(color="#176b7a"):
    stream = io.BytesIO()
    Image.new("RGB", (128, 192), color).save(stream, format="PNG")
    return SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(stream.getvalue()).decode())])


class AgentContracts(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.project = initialize_fixture(self.directory)
        self.environment = patch.dict(os.environ, {"POSTER_MODEL": "fixture-vision-model", "POSTER_IMAGE_MODEL": "gpt-image-2"})
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.temporary.cleanup()

    def test_responses_request_uses_actual_image_mime_and_completed_json(self):
        photo = self.directory / "photo.jpg"
        Image.new("RGB", (24, 20)).save(photo)
        responses = Mock()
        responses.create.return_value = SimpleNamespace(status="completed", output_text='{"value": 1}')
        with patch.object(agent, "_client", return_value=SimpleNamespace(responses=responses)):
            self.assertEqual(agent._json_role("Review", {"text": "Paper data"}, [("Original JPEG", photo)]), {"value": 1})
        arguments = responses.create.call_args.kwargs
        self.assertEqual(arguments["model"], "fixture-vision-model")
        self.assertEqual(arguments["text"], {"format": {"type": "json_object"}})
        content = arguments["input"][0]["content"]
        self.assertTrue(content[2]["image_url"].startswith("data:image/jpeg;base64,"))
        self.assertEqual(content[2]["detail"], "high")
        self.assertIn("untrusted data", arguments["instructions"])

    def test_incomplete_invalid_json_and_missing_images_fail_honestly(self):
        for status, output, expected in [("incomplete", "{}", RuntimeError), ("failed", "{}", RuntimeError),
                                          ("completed", "not JSON", ValueError), ("completed", "[]", ValueError)]:
            with self.subTest(status=status, output=output), patch.object(agent, "_client") as client:
                client.return_value.responses.create.return_value = SimpleNamespace(status=status, output_text=output)
                with self.assertRaises(expected):
                    agent._json_role("Review", {})
        with patch.object(agent, "_client") as client:
            with self.assertRaises(FileNotFoundError):
                agent._json_role("Review", {}, [("Missing required original", self.directory / "missing.png")])
            client.assert_not_called()

    def test_sdk_exception_details_and_credentials_are_never_propagated(self):
        error = RuntimeError("Authorization: Bearer sk-PRIVATE-SECRET; https://user:password@proxy.invalid")
        error.status_code = 401
        client = SimpleNamespace(responses=SimpleNamespace(create=Mock(side_effect=error)))
        with patch.object(agent, "_client", return_value=client), self.assertRaisesRegex(RuntimeError, "HTTP 401") as captured:
            agent._json_role("Review", {})
        self.assertNotIn("PRIVATE-SECRET", str(captured.exception))
        self.assertNotIn("password", str(captured.exception))

    def test_draft_uses_imported_originals_and_retains_provenance(self):
        original = self.project / "assets/original.svg"
        original.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100"><rect width="200" height="100" fill="#176b7a"/></svg>', encoding="utf-8")
        Image.new("RGB", (800, 400), "#176b7a").save(original.with_suffix(".png"))
        record = {"id": "original", "path": "assets/original.svg", "preview": "assets/original.png", "type": "svg", "source": "source/original.svg"}
        write_json(self.project / "assets/catalog.json", {"entries": [record]})
        write_json(self.project / "assets/provenance.json", [record])
        response = draft_fixture("assets/original.svg")
        response["original_assets"] = [{"id": "original", "path": "assets/original.svg"}]
        response["figure_regions"] = [{"id": "extra", "page": 1, "bbox": [.05, .1, .7, .3]}]
        with patch.object(agent, "_json_role", return_value=response):
            result = agent.draft_project(self.project)
        self.assertEqual(result["sections"][0]["image"], "assets/original.svg")
        self.assertEqual(result["canvas"], {"width_mm": 420, "height_mm": 594, "png_width": 6000})
        ledger = read_json(self.project / "assets/provenance.json")
        self.assertIn(record, ledger)
        self.assertTrue(any(item["id"] == "extra" for item in ledger))
        self.assertEqual(read_json(self.project / "evidence.json")["content_review"]["status"], "pending")

    def test_draft_rejects_invented_original_path_and_missing_evidence(self):
        response = draft_fixture()
        response["original_assets"] = [{"id": "fabricated", "path": "../outside.svg"}]
        with patch.object(agent, "_json_role", return_value=response), self.assertRaisesRegex(ValueError, "outside the actual"):
            agent.draft_project(self.project)
        self.assertFalse((self.project / "poster.json").exists())
        response = draft_fixture()
        response["poster"]["sections"][0]["source_refs"] = ["invented-reference"]
        with patch.object(agent, "_json_role", return_value=response), self.assertRaisesRegex(ValueError, "source evidence"):
            agent.draft_project(self.project)

    def test_reference_is_versioned_preserves_original_and_includes_actual_logo(self):
        with patch.object(agent, "_json_role", return_value=draft_fixture()):
            agent.draft_project(self.project)
        logo = self.project / "assets/lab.jpg"
        Image.new("RGB", (120, 20), "#17467a").save(logo)
        spec = load_spec(self.project)
        spec["branding"] = {"logo": "assets/lab.jpg"}
        spec["canvas"].update(width_mm=594, height_mm=420)
        write_json(self.project / "poster.json", spec)
        images = Mock()
        images.edit.return_value = image_response()
        with patch.object(agent, "_client", return_value=SimpleNamespace(images=images)):
            first = agent.generate_reference(self.project)
            old_bytes = Path(first["reference"]).read_bytes()
            with self.assertRaisesRegex(ValueError, "already exists"):
                agent.generate_reference(self.project)
            second = agent.generate_reference(self.project, new_version=True)
        self.assertEqual(images.edit.call_count, 2)
        self.assertEqual(images.edit.call_args.kwargs["size"], "1536x1088")
        self.assertEqual(images.edit.call_args.kwargs["image"][0].name, str(logo))
        self.assertEqual(Path(first["reference"]).read_bytes(), old_bytes)
        self.assertIn("v0002", second["reference"])
        self.assertEqual(load_spec(self.project)["version"], 2)
        self.assertEqual(load_spec(self.project)["reference_image"], "reference/design-reference-v0002.png")
        self.assertIsNone(load_spec(self.project)["approval"])

    def test_reference_invalid_api_output_keeps_previous_file(self):
        with patch.object(agent, "_json_role", return_value=draft_fixture()):
            agent.draft_project(self.project)
        original = self.project / "reference/design-reference.png"
        Image.new("RGB", (20, 30)).save(original)
        old = original.read_bytes()
        client = SimpleNamespace(images=SimpleNamespace(generate=Mock(return_value=SimpleNamespace(data=[]))))
        with patch.object(agent, "_client", return_value=client), self.assertRaisesRegex(ValueError, "no base64"):
            agent.generate_reference(self.project, new_version=True)
        self.assertEqual(original.read_bytes(), old)
        self.assertFalse((self.project / "reference/design-reference-v0002.png").exists())

    def test_native_detail_critique_checks_real_pdf_and_content_issues_need_author(self):
        with patch.object(agent, "_json_role", return_value=draft_fixture()):
            agent.draft_project(self.project)
        Image.new("RGB", (80, 120)).save(self.project / "reference/design-reference.png")
        export_project(self.project, png_width=3840)
        critique = accepted_critique()
        critique["content"] = {"status": "needs_revision", "issues": [{"section_id": "method", "severity": "error", "evidence": "Claim differs from supplied paper.", "suggestion": "Ask the author to reconcile the claim."}]}
        with patch.object(agent, "_json_role", return_value=critique) as role:
            result = agent.critique_project(self.project)
        labels = [label for label, _ in role.call_args.args[2]]
        self.assertIn("Native 4K+ HTML detail: method", labels)
        self.assertIn("Independent PDF detail: method", labels)
        crop = self.project / result["crops"][1]["html"]
        with Image.open(crop) as image:
            self.assertGreater(image.width, 3000, "Local evidence comes from native 4K render, not a thumbnail")
        self.assertFalse(result["human_acceptance"])
        digest = content_digest(load_spec(self.project))
        with patch.object(agent, "_json_role") as role:
            repair = agent.repair_project(self.project)
            role.assert_not_called()
        self.assertEqual(repair["status"], "needs_author")
        self.assertEqual(content_digest(load_spec(self.project)), digest)
        self.assertIsNone(load_spec(self.project)["approval"])

    def test_visual_repair_rejects_fact_edits_and_preserves_locks(self):
        with patch.object(agent, "_json_role", return_value=draft_fixture()):
            agent.draft_project(self.project)
        spec = load_spec(self.project)
        spec["locked_regions"] = ["method"]
        write_json(self.project / "poster.json", spec)
        critique = accepted_critique()
        critique["style"]["issues"] = [{"section_id": "method", "severity": "warning", "evidence": "The hierarchy is weak.", "suggestion": "Increase this figure height."}]
        critique.update(spec_sha256=spec_digest(spec))
        write_json(self.project / "visual-critique.json", critique)
        (self.project / "exports").mkdir(exist_ok=True)
        Image.new("RGB", (80, 120)).save(self.project / "exports/poster-preview.png")
        checks = {"issues": [], "metrics": {}}
        result = {"status": "applied", "patch": {"sections": [{"id": "method", "image_height_mm": 100}]}, "addresses": ["style-0"], "explanation": "Increase method prominence."}
        with patch("poster_agent.render.check_project", return_value=checks), patch.object(agent, "_json_role", return_value=result), self.assertRaisesRegex(ValueError, "locked"):
            agent.repair_project(self.project)
        self.assertEqual(load_spec(self.project)["version"], 1)
        spec["locked_regions"] = []
        write_json(self.project / "poster.json", spec)
        critique["spec_sha256"] = spec_digest(spec)
        write_json(self.project / "visual-critique.json", critique)
        result["patch"] = {"sections": [{"id": "method", "paragraphs": ["Invented scientific conclusion"]}]}
        with patch("poster_agent.render.check_project", return_value=checks), patch.object(agent, "_json_role", return_value=result), self.assertRaisesRegex(ValueError, "text, data"):
            agent.repair_project(self.project)
        self.assertEqual(load_spec(self.project)["sections"][0]["paragraphs"], spec["sections"][0]["paragraphs"])


if __name__ == "__main__":
    unittest.main()
