"""Browser checks of real iframe selection and truthful feedback saving."""
import tempfile
import threading
import unittest
from pathlib import Path

from playwright.sync_api import sync_playwright

from poster_agent.project import approved, content_digest, load_spec, read_json, write_json
from poster_agent.render import build_html, export_project
from poster_agent.review import create_server


class ReviewBrowserTest(unittest.TestCase):
    def test_selection_feedback_and_preserved_region(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            spec = {"schema_version": 1, "version": 1, "status": "review", "title": "A practical poster",
                    "canvas": {"width_mm": 841, "height_mm": 1189}, "conference": {"name": "Example", "year": 2026},
                    "sections": [{"id": "method", "heading": "Method", "kind": "text", "span": 2,
                                  "paragraphs": ["A verified method statement"], "source_refs": ["method"]}],
                    "locked_regions": [], "approval": None}
            write_json(project / "poster.json", spec)
            write_json(project / "conference.json", {"requirements": {}, "sources": [], "unresolved": ["Size unknown"]})
            write_json(project / "evidence.json", {"paper": {}, "items": [], "content_review": {"status": "pending"}})
            build_html(project)
            server = create_server(project, port=0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch()
                    page = browser.new_page(viewport={"width": 1600, "height": 1000})
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.goto(f"http://127.0.0.1:{server.server_port}")
                    page.wait_for_function("document.querySelector('#versionBadge').textContent.includes('v1')")
                    frame = page.frame_locator("#posterFrame")
                    frame.locator("[data-section-id=method]").click()
                    self.assertIn("Method", page.locator("#targetLabel").inner_text())
                    self.assertTrue(page.locator("#selection").is_visible())
                    page.locator("#rectMode").click()
                    bounds = frame.locator("[data-section-id=method]").bounding_box()
                    page.mouse.move(bounds["x"] + 8, bounds["y"] + 8)
                    page.mouse.down()
                    page.mouse.move(bounds["x"] + 65, bounds["y"] + min(30, bounds["height"] - 2), steps=5)
                    page.mouse.up()
                    self.assertIn("已框选区域", page.locator("#targetLabel").inner_text())
                    page.locator("#feedbackText").fill("Make the method more prominent; keep the title.")
                    page.locator("#saveFeedbackButton").click()
                    page.wait_for_function("document.querySelector('#notice').textContent.includes('反馈已保存')")
                    feedback = read_json(project / "feedback.json")[0]
                    self.assertEqual(feedback["target"], "method")
                    self.assertEqual(len(feedback["bbox"]), 4)
                    self.assertTrue(all(0 <= value <= 1 for value in feedback["bbox"]))
                    self.assertEqual(load_spec(project)["version"], 1)
                    self.assertTrue(page.locator("#applyButton").is_enabled())
                    self.assertFalse(page.locator("#approveButton").is_enabled())
                    page.locator("#lockList input[value=header]").check()
                    page.locator("#saveLocksButton").click()
                    page.wait_for_function("document.querySelector('#versionBadge').textContent.includes('v2')")
                    self.assertIn("header", load_spec(project)["locked_regions"])
                    self.assertFalse(errors, errors)
                    browser.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

    def test_deliberate_confirmation_freezes_until_explicitly_reopened(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            spec = {"schema_version": 1, "version": 1, "status": "review", "title": "A verified poster",
                    "canvas": {"width_mm": 420, "height_mm": 594, "png_width": 3840},
                    "sections": [{"id": "method", "heading": "Method", "kind": "text", "span": 2,
                                  "paragraphs": ["A verified method statement"], "source_refs": ["method"]}],
                    "locked_regions": [], "approval": None}
            write_json(project / "poster.json", spec)
            write_json(project / "conference.json", {"requirements": {"width_mm": 420, "height_mm": 594},
                                                       "sources": [{"url": "https://example.invalid/test-guidelines", "scope": "test fixture"}], "unresolved": []})
            write_json(project / "evidence.json", {"paper": {"title": spec["title"]},
                                                     "items": [{"id": "method", "page": 1, "text": "A verified method statement"}],
                                                     "content_review": {"status": "accepted", "issues": [], "content_sha256": content_digest(spec)}})
            report = export_project(project, png_width=3840)
            self.assertTrue(report["technical_pass"], report["issues"])
            self.assertFalse(approved(load_spec(project)))
            server = create_server(project, port=0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch()
                    page = browser.new_page(viewport={"width": 1600, "height": 1000})
                    page.goto(f"http://127.0.0.1:{server.server_port}")
                    page.wait_for_function("!document.querySelector('#approveButton').disabled")
                    page.locator("#approveButton").click()
                    self.assertTrue(page.locator("#confirmApprove").is_disabled())
                    page.locator("#contentConfirm").check()
                    self.assertTrue(page.locator("#confirmApprove").is_disabled())
                    page.locator("#designConfirm").check()
                    page.locator("#confirmApprove").click()
                    page.wait_for_function("document.querySelector('#versionBadge').textContent.includes('已确认')")
                    self.assertTrue(approved(load_spec(project)))
                    self.assertTrue(page.locator("#saveLocksButton").is_disabled())
                    self.assertTrue(page.locator("#applyButton").is_disabled())
                    self.assertTrue(page.locator("#undoButton").is_disabled())
                    self.assertTrue(page.locator("#reopenButton").is_visible())
                    page.locator("#reopenButton").click()
                    page.wait_for_function("document.querySelector('#versionBadge').textContent.includes('待审阅')")
                    self.assertFalse(approved(load_spec(project)))
                    self.assertTrue(page.locator("#saveLocksButton").is_enabled())
                    browser.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join()


if __name__ == "__main__":
    unittest.main()
