"""Delivery tests use real Chromium artifacts and real approval/content gates."""
import copy
import io
import json
import shutil
import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import fitz
from PIL import Image

from poster_agent.delivery import package_project
from poster_agent.project import approve, content_digest, load_spec, read_json, reopen, write_json
from poster_agent.render import check_project, export_project


class FrozenDate(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 10, 8, 12, tzinfo=tz)


class DeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.base = Path(cls.temporary.name) / "fixture"
        (cls.base / "assets").mkdir(parents=True)
        (cls.base / "source").mkdir()
        Image.new("RGB", (2000, 1000), "#176b7a").save(cls.base / "assets/original.png")
        paper = fitz.open()
        paper.new_page().insert_text((40, 60), "The fixture tests exact PDF dimensions and original images.")
        paper.save(cls.base / "source/private-paper.pdf")
        paper.close()
        cls.spec = {"schema_version": 1, "version": 1, "status": "review",
            "conference": {"name": "Delivery Fixture", "year": 2026, "track": "Main"},
            "canvas": {"width_mm": 420, "height_mm": 594, "png_width": 3840},
            "title": "Exact-size poster delivery", "authors": "Fixture Researcher",
            "layout": {"style": "narrative", "columns": 1, "title_pt": 36, "body_pt": 18},
            "sections": [{"id": "evidence", "heading": "Measured print geometry", "span": 1,
                "paragraphs": ["The fixture tests exact PDF dimensions and original images."],
                "image": "assets/original.png", "image_height_mm": 55, "source_refs": ["p1"]}],
            "approval": None}
        cls.conference = {"identity": cls.spec["conference"], "sources": [{"url": "https://example.org/presenter", "title": "Test fixture requirements"}],
            "requirements": {"width_mm": 420, "height_mm": 594, "orientation": "portrait", "format": "PDF", "min_ppi": 150},
            "unresolved": [], "printing_service": {"template": "ACMMM2026_Poster_{track}_{paper_id}.pdf", "deadline_date": "2026-11-01"}}
        write_json(cls.base / "poster.json", cls.spec)
        write_json(cls.base / "conference.json", cls.conference)
        write_json(cls.base / "evidence.json", {"paper": {"title": cls.spec["title"], "path": str(cls.base / "source/private-paper.pdf")},
            "items": [{"id": "p1", "page": 1, "text": cls.spec["sections"][0]["paragraphs"][0]}],
            "content_review": {"status": "accepted", "issues": [], "content_sha256": content_digest(cls.spec)}})
        report = export_project(cls.base)
        if not report["technical_pass"] or not report["content_pass"]:
            raise AssertionError(report["issues"])

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def setUp(self):
        self.case = tempfile.TemporaryDirectory()
        self.addCleanup(self.case.cleanup)
        self.project = Path(self.case.name) / "poster"
        shutil.copytree(self.base, self.project)
        check_project(self.project)
        approve(self.project)  # Deliberate test reviewer action; real user examples stay unapproved.

    def test_checked_print_package_contains_only_handoff_and_exact_page(self):
        (self.project / "history").mkdir()
        (self.project / "history/private.txt").write_text("private history")
        write_json(self.project / "feedback.json", [{"message": "private feedback"}])
        conference = read_json(self.project / "conference.json")
        conference["warnings"] = [f"Original workspace C:/private/secret-source; credential sk-test-secret."]
        conference["private_note"] = "must not package"
        write_json(self.project / "conference.json", conference)
        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test-secret"}):
            destination = package_project(self.project)
        self.assertEqual(destination.name, "print-package-v0001.zip")
        with zipfile.ZipFile(destination) as archive:
            self.assertEqual(set(archive.namelist()), {"poster-print.pdf", "poster.html", "poster-4k.png", "quality-report.json", "PRINT_README.txt"})
            with fitz.open(stream=archive.read("poster-print.pdf"), filetype="pdf") as pdf:
                self.assertEqual(len(pdf), 1)
                self.assertAlmostEqual(pdf[0].rect.width * 25.4 / 72, 420, delta=.001)
                self.assertAlmostEqual(pdf[0].rect.height * 25.4 / 72, 594, delta=.001)
            with Image.open(io.BytesIO(archive.read("poster-4k.png"))) as image:
                self.assertEqual(image.width, 3840)
            self.assertNotIn('src="http', archive.read("poster.html").decode())
            report = json.loads(archive.read("quality-report.json"))
            self.assertTrue(report["print_ready"])
            text = archive.read("PRINT_README.txt").decode()
            self.assertIn("exact version 1", text)
            self.assertIn("https://example.org/presenter", text)
            for private in ("C:/private/", "sk-test-secret", "private-note", "private feedback"):
                self.assertNotIn(private, text)

    def test_no_package_without_exact_human_content_and_artifact_approval(self):
        reopen(self.project)
        with self.assertRaisesRegex(ValueError, "human_approval_current"):
            package_project(self.project)
        self.assertFalse(list((self.project / "exports").glob("*.zip")))
        check_project(self.project)
        approve(self.project)
        evidence = read_json(self.project / "evidence.json")
        evidence["content_review"]["status"] = "pending"
        write_json(self.project / "evidence.json", evidence)
        with self.assertRaisesRegex(ValueError, "content_accepted"):
            package_project(self.project)

    def test_stale_actual_export_and_unapproved_spec_are_blocked(self):
        (self.project / "exports/poster.html").write_text("modified after export")
        with self.assertRaisesRegex(ValueError, "current_export"):
            package_project(self.project)

    def test_a_model_visual_acceptance_is_not_recorded_human_review(self):
        spec = load_spec(self.project)
        spec["visual_review"]["reviewer"] = "model"
        write_json(self.project / "poster.json", spec)
        with self.assertRaisesRegex(ValueError, "human visual reviewer"):
            package_project(self.project)

    def test_configured_credential_cannot_be_copied_from_an_approved_artifact(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": self.spec["title"]}), self.assertRaisesRegex(ValueError, "configured credential"):
            package_project(self.project)
        self.assertFalse(list((self.project / "exports").glob("*.zip")))

    def test_service_names_need_actual_values_and_support_current_legacy_profile(self):
        with patch("poster_agent.delivery.datetime", FrozenDate):
            with self.assertRaisesRegex(ValueError, "paper_id, track"):
                package_project(self.project, printing_service=True)
            output = package_project(self.project, printing_service=True, paper_id="AB12", track="Main")
        with zipfile.ZipFile(output) as archive:
            self.assertIn("ACMMM2026_Poster_Main_AB12.pdf", archive.namelist())
        conference = copy.deepcopy(self.conference)
        conference["requirements"]["file_name"] = "ACMMM2026_Poster_Track_OpenReviewID.pdf"
        del conference["printing_service"]["template"]
        write_json(self.project / "conference.json", conference)
        with patch("poster_agent.delivery.datetime", FrozenDate):
            output = package_project(self.project, printing_service=True, paper_id="CD34", track="Main")
        with zipfile.ZipFile(output) as archive:
            self.assertIn("ACMMM2026_Poster_Main_CD34.pdf", archive.namelist())

    def test_path_and_reserved_filename_rejected_before_writing(self):
        for name in ("../elsewhere.pdf", "sub/final.pdf", "C:\\final.pdf", "CON.pdf", "bad.txt", " .pdf"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "filename"):
                package_project(self.project, filename=name)
        with patch("poster_agent.delivery.datetime", FrozenDate), self.assertRaisesRegex(ValueError, "letters, digits"):
            package_project(self.project, printing_service=True, paper_id="../escape", track="Main")
        self.assertFalse(list((self.project / "exports").glob("*.zip")))

    def test_official_mandatory_filename_is_applied_without_selecting_service(self):
        conference = copy.deepcopy(self.conference)
        conference["requirements"]["file_name"] = "Conference2026_{track}_{paper_id}.pdf"
        conference["requirement_sources"] = {"file_name": [0]}
        conference["sources"][0].update(category="mandatory_poster", verification="fetched_quote_matched")
        write_json(self.project / "conference.json", conference)
        with self.assertRaisesRegex(ValueError, "mandatory conference filename values: paper_id, track"):
            package_project(self.project)
        output = package_project(self.project, paper_id="P42", track="Main")
        with zipfile.ZipFile(output) as archive:
            self.assertIn("Conference2026_Main_P42.pdf", archive.namelist())
        with self.assertRaisesRegex(ValueError, "rules require filename"):
            package_project(self.project, filename="user-override.pdf", paper_id="P42", track="Main")

    def test_nested_service_rules_allow_maximum_dimensions_and_either_orientation(self):
        conference = copy.deepcopy(self.conference)
        conference["printing_service"] = {"requirements": {"dimension_policy": "maximum", "width_mm": 841,
            "height_mm": 1189, "orientation": "either", "format": "PDF", "max_file_size_mb": 10,
            "file_name": "Print_{track}_{paper_id}.pdf", "deadline_date": "2026-11-01"}}
        write_json(self.project / "conference.json", conference)
        with patch("poster_agent.delivery.datetime", FrozenDate):
            output = package_project(self.project, printing_service=True, paper_id="P42", track="Main")
        with zipfile.ZipFile(output) as archive:
            self.assertIn("Print_Main_P42.pdf", archive.namelist())
            self.assertIn('"dimension_policy": "maximum"', archive.read("PRINT_README.txt").decode())

    def test_unverified_service_rules_block_service_and_do_not_block_local_handoff(self):
        conference = copy.deepcopy(self.conference)
        conference["printing_service"]["unresolved_rules"] = ["format: optional printing-service evidence is unconfirmed"]
        write_json(self.project / "conference.json", conference)
        self.assertTrue(package_project(self.project).exists())
        with self.assertRaisesRegex(ValueError, "remain unverified: format"):
            package_project(self.project, printing_service=True, paper_id="AB12", track="Main")

    def test_selected_service_constraints_are_measured_and_deadline_scoped(self):
        conference = copy.deepcopy(self.conference)
        conference["printing_service"]["deadline_date"] = "2026-10-01"
        write_json(self.project / "conference.json", conference)
        with patch("poster_agent.delivery.datetime", FrozenDate):
            self.assertTrue(package_project(self.project).exists())
            with self.assertRaisesRegex(ValueError, "deadline.*passed"):
                package_project(self.project, printing_service=True, paper_id="AB12", track="Main")
        conference["printing_service"]["deadline_date"] = "2026-11-01"
        for field, value, expected in (("width_mm", 841, "width_mm"), ("max_file_size_mb", .00001, "exceeding"),
                                        ("format", "PNG", "does not support PDF"), ("min_ppi", 10000, "min_ppi")):
            with self.subTest(field=field):
                selected = copy.deepcopy(conference)
                selected["printing_service"][field] = value
                write_json(self.project / "conference.json", selected)
                with patch("poster_agent.delivery.datetime", FrozenDate), self.assertRaisesRegex(ValueError, expected):
                    package_project(self.project, printing_service=True, paper_id="AB12", track="Main")

    def test_demo_profiles_and_unsupported_conference_format_are_not_certified(self):
        conference = copy.deepcopy(self.conference)
        conference["is_demo"] = True
        write_json(self.project / "conference.json", conference)
        with self.assertRaisesRegex(ValueError, "Demo"):
            package_project(self.project)
        conference["is_demo"] = False
        conference["requirements"]["format"] = "PNG"
        write_json(self.project / "conference.json", conference)
        with self.assertRaisesRegex(ValueError, "does not support PDF"):
            package_project(self.project)


if __name__ == "__main__":
    unittest.main()
