"""Real local PDF/browser end-to-end workflow with paid roles replaced by fixtures."""
import copy
import hashlib
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
from poster_agent.pipeline import run_pipeline
from poster_agent.project import (apply_visual_patch, content_digest, load_spec, read_json,
                                  spec_digest, write_json)

from test_agent import accepted_critique, draft_fixture, image_response, initialize_fixture


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.project = initialize_fixture(self.directory)
        self.model_calls = []
        self.review_calls = 0
        self.environment = patch.dict(os.environ, {"POSTER_MODEL": "fixture-vision-model", "POSTER_IMAGE_MODEL": "gpt-image-2"})
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.temporary.cleanup()

    def fake_role(self, instructions, context, images=(), tools=None):
        self.model_calls.append(instructions.split(".")[0])
        if instructions.startswith("You are a scientific"):
            draft = draft_fixture("assets/method.svg")
            draft["figure_regions"] = [{"id": "method", "page": 1, "bbox": [.07, .15, .79, .31]}]
            return draft
        if instructions.startswith("You are an independent"):
            self.review_calls += 1
            result = accepted_critique()
            if self.review_calls == 1:
                result["style"]["issues"] = [{"section_id": "method", "severity": "warning", "evidence": "The method figure is too short for its labels.", "suggestion": "Increase method height from 60 to 70 mm."}]
            self.assertTrue(any("Native 4K+ HTML detail" in label for label, _ in images))
            return result
        if instructions.startswith("Repair"):
            return {"status": "applied", "patch": {"sections": [{"id": "method", "image_height_mm": 70}]},
                    "addresses": ["style-0"], "explanation": "Increase method detail while preserving original figures and all facts."}
        raise AssertionError("Unexpected API role")

    def api_patches(self):
        images = SimpleNamespace(edit=Mock(return_value=image_response()), generate=Mock(return_value=image_response()))
        return patch.object(agent, "_json_role", side_effect=self.fake_role), patch.object(agent, "_client", return_value=SimpleNamespace(images=images))

    def test_complete_real_pipeline_repair_and_resume_preserve_exact_artifacts(self):
        roles, client = self.api_patches()
        paper_digest = hashlib.sha256((self.project / "source/paper.pdf").read_bytes()).hexdigest()
        with roles, client:
            report = run_pipeline(self.project)
        self.assertEqual(report["status"], "awaiting_human_review", report)
        self.assertEqual(report["repair_rounds"], 1)
        self.assertEqual(report["version"], 2)
        self.assertTrue(report["technical_pass"])
        self.assertTrue(report["content_pass"])
        self.assertFalse(report["print_ready"])
        self.assertIsNone(load_spec(self.project)["approval"])
        self.assertEqual(hashlib.sha256((self.project / "source/paper.pdf").read_bytes()).hexdigest(), paper_digest)
        self.assertTrue((self.project / "history/v0001.json").is_file())
        self.assertTrue((self.project / "exports/review-crops/method-pdf.png").is_file())
        with fitz.open(self.project / "exports/poster-print.pdf") as pdf:
            self.assertEqual(len(pdf), 1)
            self.assertAlmostEqual(pdf[0].rect.width * 25.4 / 72, 420, delta=.001)
            self.assertIn("controlled comparison", pdf[0].get_text())
        with Image.open(self.project / "exports/poster-4k.png") as image:
            self.assertEqual(image.width, 6000)
        originals = {name: (self.project / name).read_bytes() for name in ["reference/design-reference.png", "assets/method.svg", "source/paper.pdf", "exports/poster-print.pdf"]}
        with patch.object(agent, "_json_role") as role, patch.object(agent, "_client") as client:
            resumed = run_pipeline(self.project, resume=True)
            role.assert_not_called()
            client.assert_not_called()
        self.assertEqual(resumed["status"], "awaiting_human_review")
        for name, data in originals.items():
            self.assertEqual((self.project / name).read_bytes(), data)
        self.assertEqual(load_spec(self.project)["version"], 2)

    def test_failed_reference_records_safe_next_step_and_resume_reuses_draft(self):
        raw_error = RuntimeError("Bearer sk-DO-NOT-RECORD-THIS; https://user:private-password@proxy.invalid")
        raw_error.status_code = 429
        client = SimpleNamespace(images=SimpleNamespace(edit=Mock(side_effect=raw_error)))
        with patch.object(agent, "_json_role", side_effect=self.fake_role), patch.object(agent, "_client", return_value=client):
            with self.assertRaisesRegex(RuntimeError, "failed at reference"):
                run_pipeline(self.project, max_rounds=0)
        failed = read_json(self.project / "run-report.json")
        self.assertEqual(failed["failed_step"], "reference")
        self.assertEqual(failed["status"], "failed")
        self.assertIn("resume", failed["next_action"])
        self.assertNotIn("DO-NOT-RECORD", (self.project / "run-report.json").read_text(encoding="utf-8"))
        self.assertNotIn("private-password", failed["error"])
        initial = (self.project / "poster.json").read_bytes()
        roles, client = self.api_patches()
        with roles, client, patch.object(agent, "draft_project") as draft:
            report = run_pipeline(self.project, resume=True, max_rounds=0)
            draft.assert_not_called()
        self.assertEqual((self.project / "poster.json").read_bytes(), initial)
        self.assertEqual(report["status"], "awaiting_human_review")
        self.assertEqual(report["repair_rounds"], 0)

    def test_two_visual_rounds_have_a_hard_end_and_never_approve(self):
        def role(instructions, context, images=(), tools=None):
            if instructions.startswith("You are an independent"):
                self.review_calls += 1
                result = accepted_critique()
                result["style"]["issues"] = [{"section_id": "method", "severity": "warning", "evidence": "A source label needs more visual prominence.", "suggestion": "Increase the method figure height by 10 mm."}]
                return result
            if instructions.startswith("Repair"):
                height = context["poster"]["sections"][0]["image_height_mm"]
                return {"status": "applied", "patch": {"sections": [{"id": "method", "image_height_mm": height + 10}]}, "addresses": ["style-0"], "explanation": "Increase method label prominence."}
            return self.fake_role(instructions, context, images, tools)
        _, client = self.api_patches()
        with patch.object(agent, "_json_role", side_effect=role), client:
            report = run_pipeline(self.project, max_rounds=2)
        self.assertEqual(report["repair_rounds"], 2)
        self.assertEqual(self.review_calls, 3)
        self.assertEqual(load_spec(self.project)["version"], 3)
        self.assertTrue(report["automatic_revision_limit_reached"])
        self.assertFalse(report["print_ready"])
        self.assertIsNone(load_spec(self.project)["approval"])
        with patch.object(agent, "_json_role") as role:
            resumed = run_pipeline(self.project, resume=True, max_rounds=2)
            role.assert_not_called()
        self.assertEqual(resumed["repair_rounds"], 2)

    def test_source_replacement_and_nonresume_cannot_overwrite_existing_work(self):
        with patch.object(agent, "_json_role", side_effect=self.fake_role), patch.object(agent, "generate_reference", side_effect=RuntimeError("No API key")):
            with self.assertRaises(RuntimeError):
                run_pipeline(self.project)
        with self.assertRaisesRegex(ValueError, "select resume"):
            run_pipeline(self.project)
        (self.project / "source/paper.pdf").write_bytes(b"changed source")
        with patch.object(agent, "_json_role") as role, self.assertRaisesRegex(RuntimeError, "Original paper bytes changed"):
            run_pipeline(self.project, resume=True)
        role.assert_not_called()
        self.assertEqual(read_json(self.project / "run-report.json")["failed_step"], "source")

    def test_content_issue_stops_for_author_without_visual_revision(self):
        def role(instructions, context, images=(), tools=None):
            if instructions.startswith("You are an independent"):
                result = accepted_critique()
                result["content"] = {"status": "needs_revision", "issues": [{"section_id": "method", "severity": "error", "evidence": "The poster misstates the source result.", "suggestion": "Verify the source value with the author."}]}
                return result
            return self.fake_role(instructions, context, images, tools)
        _, client = self.api_patches()
        with patch.object(agent, "_json_role", side_effect=role), client:
            report = run_pipeline(self.project)
        self.assertEqual(report["status"], "needs_author")
        self.assertEqual(report["repair_rounds"], 0)
        self.assertEqual(load_spec(self.project)["version"], 1)
        self.assertFalse(report["content_pass"])
        self.assertFalse(report["print_ready"])

    def test_round_limit_is_enforced_and_unresolved_technical_failures_stay_visible(self):
        for invalid in (-1, 3, True, 1.5):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, "0 to 2"):
                run_pipeline(self.project, max_rounds=invalid)
        # A full local chain must not relabel clipping as print-ready success.
        def role(instructions, context, images=(), tools=None):
            result = self.fake_role(instructions, context, images, tools)
            if instructions.startswith("You are a scientific"):
                result["poster"]["sections"][0]["image_height_mm"] = 900
            return result
        _, client = self.api_patches()
        with patch.object(agent, "_json_role", side_effect=role), client:
            report = run_pipeline(self.project, max_rounds=0)
        self.assertEqual(report["status"], "needs_manual_fix")
        self.assertFalse(report["technical_pass"])
        self.assertFalse(report["print_ready"])
        self.assertEqual(report["repair_rounds"], 0)


if __name__ == "__main__":
    unittest.main()
