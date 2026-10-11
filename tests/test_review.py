import http.client
import copy
import io
import json
import shutil
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from poster_agent.project import load_spec, spec_digest, write_json
from poster_agent.review import create_server


class LocalReviewTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary.name) / "project"
        self.project.mkdir()
        self.spec = {"schema_version": 1, "version": 1, "status": "review",
                     "title": "A verified poster", "canvas": {"width_mm": 841, "height_mm": 1189},
                     "sections": [{"id": "method", "heading": "Method", "kind": "text",
                                   "paragraphs": ["Verified method"], "source_refs": ["method"]}],
                     "locked_regions": [], "approval": None}
        write_json(self.project / "poster.json", self.spec)
        (self.project / "exports").mkdir()
        (self.project / "exports" / "poster.html").write_text("<p>Actual poster</p>", encoding="utf-8")
        (Path(self.temporary.name) / "private.txt").write_text("outside boundary", encoding="utf-8")
        self.server = create_server(self.project, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.origin = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temporary.cleanup()

    def request(self, method, path, data=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        request_headers = dict(headers or {})
        body = None
        if data is not None:
            body = json.dumps(data)
            request_headers.setdefault("Content-Type", "application/json")
        connection.request(method, path, body, request_headers)
        response = connection.getresponse()
        result = response.read()
        status = response.status
        content_type = response.getheader("Content-Type")
        connection.close()
        return status, json.loads(result) if content_type.startswith("application/json") else result

    def revision(self, **extra):
        return {"expected_version": self.spec["version"], "expected_digest": spec_digest(self.spec), **extra}

    def test_real_ui_and_project_file(self):
        status, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("保存反馈".encode(), body)
        self.assertIn(b"sandbox=\"allow-same-origin\"", body)
        status, body = self.request("GET", "/project/exports/poster.html")
        self.assertEqual((status, body), (200, b"<p>Actual poster</p>"))
        status, state = self.request("GET", "/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(state["spec"]["version"], 1)
        self.assertFalse(state["report_current"])

    def test_path_boundary_and_host(self):
        for path in ("/project/../private.txt", "/project/%2e%2e/private.txt", "/project/%2e%2e%5cprivate.txt"):
            status, _ = self.request("GET", path)
            self.assertEqual(status, 403, path)
        status, _ = self.request("GET", "/api/state", headers={"Host": "untrusted.example"})
        self.assertEqual(status, 403)

    def test_mutations_require_same_origin(self):
        data = self.revision(target="method", message="Enlarge this figure")
        for origin in (None, "https://untrusted.example", "null"):
            headers = {"Origin": origin} if origin else {}
            status, _ = self.request("POST", "/api/feedback", data, headers)
            self.assertEqual(status, 403)
        self.assertFalse((self.project / "feedback.json").exists())

    def test_feedback_is_saved_but_does_not_modify_poster(self):
        data = self.revision(target="poster", message="Please give the method more space",
                             bbox={"x": .1, "y": .2, "width": .3, "height": .4})
        status, response = self.request("POST", "/api/feedback", data, {"Origin": self.origin})
        self.assertEqual(status, 200)
        self.assertTrue(response["saved"])
        self.assertFalse(response["applied"])
        self.assertEqual(response["feedback"]["target"], "global")
        self.assertEqual(response["feedback"]["bbox"], [.1, .2, .3, .4])
        self.assertEqual(load_spec(self.project), self.spec)

    def test_stale_feedback_is_rejected(self):
        data = self.revision(target="method", message="Enlarge", expected_version=0)
        status, _ = self.request("POST", "/api/feedback", data, {"Origin": self.origin})
        self.assertEqual(status, 409)
        self.assertFalse((self.project / "feedback.json").exists())

    def test_missing_api_key_preserves_feedback_and_explains_codex_path(self):
        status, record = self.request("POST", "/api/feedback",
                                      self.revision(target="method", message="Enlarge the method"),
                                      {"Origin": self.origin})
        self.assertEqual(status, 200)
        with patch.dict("os.environ", {"OPENAI_API_KEY": "", "POSTER_MODEL": ""}):
            status, response = self.request("POST", "/api/apply",
                                            self.revision(feedback_id=record["feedback"]["id"]),
                                            {"Origin": self.origin})
        self.assertEqual(status, 422)
        self.assertIn("反馈已保留", response["error"])
        self.assertIn("Codex", response["error"])
        self.assertEqual(load_spec(self.project), self.spec)
        self.assertEqual(json.loads((self.project / "feedback.json").read_text(encoding="utf-8"))[0]["status"], "pending")

    def test_invalid_selection_and_region_are_rejected(self):
        for change in ({"target": "invented"}, {"bbox": {"x": .9, "y": .1, "width": .2, "height": .1}},
                       {"bbox": {"x": True, "y": .1, "width": .1, "height": .1}}):
            data = self.revision(target="method", message="Enlarge", **{k:v for k,v in change.items() if k != "target"})
            if "target" in change:
                data["target"] = change["target"]
            status, _ = self.request("POST", "/api/feedback", data, {"Origin": self.origin})
            self.assertEqual(status, 400)
        self.assertFalse((self.project / "feedback.json").exists())

    def test_approval_rechecks_real_project_and_rejects_missing_outputs(self):
        write_json(self.project / "conference.json", {"requirements": {}, "sources": [], "unresolved": ["Size unknown"]})
        write_json(self.project / "evidence.json", {"paper": {}, "items": [], "content_review": {"status": "pending"}})
        write_json(self.project / "exports" / "quality-report.json",
                   {"version": 1, "spec_sha256": spec_digest(self.spec),
                    "required_checks": [{"id": "old_fake_check", "passed": True}]})
        status, _ = self.request("POST", "/api/approve", self.revision(), {"Origin": self.origin})
        self.assertEqual(status, 422)
        self.assertIsNone(load_spec(self.project)["approval"])
        report = json.loads((self.project / "exports" / "quality-report.json").read_text(encoding="utf-8"))
        self.assertFalse(report["technical_pass"])
        self.assertNotEqual(report["required_checks"][0]["id"], "old_fake_check")


class CheckedPrintReviewTest(unittest.TestCase):
    """HTTP download/revision gates run against genuinely rendered print files."""
    @classmethod
    def setUpClass(cls):
        import fitz
        from poster_agent.project import content_digest
        from poster_agent.render import export_project
        cls.temporary = tempfile.TemporaryDirectory()
        cls.base = Path(cls.temporary.name) / "fixture"
        (cls.base / "source").mkdir(parents=True)
        source = fitz.open()
        source.new_page().insert_text((40, 60), "Actual page size is measured independently.")
        source.save(cls.base / "source/paper.pdf")
        source.close()
        cls.initial = {"schema_version": 1, "version": 1, "status": "review", "title": "Actual print review",
            "canvas": {"width_mm": 420, "height_mm": 594, "png_width": 3840},
            "layout": {"style": "narrative", "columns": 1, "title_pt": 36, "body_pt": 18},
            "sections": [{"id": "method", "heading": "Print evidence", "span": 1,
                "paragraphs": ["Actual page size is measured independently."], "source_refs": ["p1"]}],
            "locked_regions": [], "approval": None}
        write_json(cls.base / "poster.json", cls.initial)
        write_json(cls.base / "conference.json", {"requirements": {"width_mm": 420, "height_mm": 594, "format": "PDF"},
            "sources": [{"url": "https://example.org/fixture", "scope": "local test fixture"}], "unresolved": []})
        write_json(cls.base / "evidence.json", {"paper": {"path": "source/paper.pdf", "title": cls.initial["title"]},
            "items": [{"id": "p1", "page": 1, "text": cls.initial["sections"][0]["paragraphs"][0]}],
            "content_review": {"status": "accepted", "issues": [], "content_sha256": content_digest(cls.initial)}})
        report = export_project(cls.base)
        if not report["technical_pass"] or not report["content_pass"]:
            raise AssertionError(report["issues"])

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def setUp(self):
        self.case = tempfile.TemporaryDirectory()
        self.project = Path(self.case.name) / "poster"
        shutil.copytree(self.base, self.project)
        self.spec = copy.deepcopy(self.initial)
        self.server = create_server(self.project, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.origin = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.case.cleanup()

    request = LocalReviewTest.request
    revision = LocalReviewTest.revision

    def test_unapproved_package_post_does_not_generate_or_download_zip(self):
        status, response = self.request("POST", "/api/package", self.revision(), {"Origin": self.origin})
        self.assertEqual(status, 400)
        self.assertIn("human_approval_current", response["error"])
        self.assertFalse(list((self.project / "exports").glob("*.zip")))

    def test_approved_download_is_real_pdf_then_reopen_revokes_old_url(self):
        import fitz
        status, response = self.request("POST", "/api/approve", self.revision(), {"Origin": self.origin})
        self.assertEqual(status, 200, response)
        status, response = self.request("POST", "/api/package", self.revision(), {"Origin": self.origin})
        self.assertEqual(status, 200, response)
        url = response["download_url"]
        self.assertTrue(url.startswith("/api/print-package?"))
        status, body = self.request("GET", url)
        self.assertEqual(status, 200)
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            self.assertIn("poster-print.pdf", archive.namelist())
            with fitz.open(stream=archive.read("poster-print.pdf"), filetype="pdf") as pdf:
                self.assertEqual(len(pdf), 1)
                self.assertAlmostEqual(pdf[0].rect.width * 25.4 / 72, 420, delta=.001)
                self.assertAlmostEqual(pdf[0].rect.height * 25.4 / 72, 594, delta=.001)
        status, _ = self.request("GET", "/project/exports/print-package-v0001.zip")
        self.assertEqual(status, 403)
        status, response = self.request("POST", "/api/reopen", self.revision(), {"Origin": self.origin})
        self.assertEqual(status, 200, response)
        status, _ = self.request("GET", url)
        self.assertIn(status, (400, 403, 409))

    def test_refresh_preserves_real_previous_html_and_live_button_states(self):
        from playwright.sync_api import sync_playwright
        original_html = (self.project / "exports/poster.html").read_bytes()
        status, response = self.request("POST", "/api/locks", self.revision(locked_regions=["header"]), {"Origin": self.origin})
        self.assertEqual(status, 200, response)
        self.spec = load_spec(self.project)
        self.assertEqual(self.spec["version"], 2)
        status, state = self.request("GET", "/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(state["previous_html_url"], "/project/history/v0001.html")
        self.assertTrue(state["report_current"])
        self.assertTrue(state["report"]["technical_pass"], state["report"]["issues"])
        status, body = self.request("GET", state["previous_html_url"])
        self.assertEqual((status, body), (200, original_html))
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                page = browser.new_page(viewport={"width": 1600, "height": 1000})
                page.goto(self.origin)
                page.wait_for_function("document.querySelector('#versionBadge').textContent.includes('v2')")
                self.assertTrue(page.locator("#beforeTab").is_enabled())
                self.assertTrue(page.locator("#approveButton").is_enabled())
                self.assertTrue(page.locator("#packageButton").is_disabled())
                page.locator("#beforeTab").click()
                page.frame_locator("#posterFrame").locator("#poster").wait_for()
                status, response = self.request("POST", "/api/approve", self.revision(), {"Origin": self.origin})
                self.assertEqual(status, 200, response)
                page.locator("#refreshButton").click()
                page.wait_for_function("document.querySelector('#versionBadge').textContent.includes('已确认')")
                self.assertTrue(page.locator("#packageButton").is_enabled())
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()
