"""Scientific review and preserved regions survive only applicable revisions."""
import copy
import tempfile
import unittest
from pathlib import Path

from poster_agent.project import (apply_visual_patch, content_digest, load_spec, read_json,
                                  reopen, save_revision, spec_digest, write_json)
from poster_agent.render import check_project


class RevisionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary.name)
        self.spec = {"schema_version": 1, "version": 1, "status": "review",
                     "title": "Evidence-grounded results", "subtitle": "A measured improvement",
                     "authors": "Author", "affiliations": "Institution", "footer": "Research scope",
                     "canvas": {"width_mm": 420, "height_mm": 594},
                     "theme": {"accent": "#087b76"},
                     "layout": {"columns": 2, "gap_mm": 10, "body_pt": 25, "style": "narrative"},
                     "sections": [{"id": "method", "heading": "Method", "kind": "text", "span": 1,
                                   "paragraphs": ["A verified method"], "source_refs": ["paper"]},
                                  {"id": "results", "heading": "Results", "kind": "table", "span": 1,
                                   "rows": [["Metric", "Value"], ["Accuracy", "0.89"]],
                                   "tables": [{"title": "Controlled experiment", "rows": [["Method", "Value"], ["Ours", "0.89"]],
                                               "caption": "The training setting is fixed.", "highlight_rows": [1]}],
                                   "source_refs": ["paper"]}],
                     "locked_regions": [], "approval": None}
        write_json(self.project / "poster.json", self.spec)
        self.evidence = {"paper": {"title": self.spec["title"]}, "items": [{"id": "paper", "page": 1}],
                         "content_review": {"status": "accepted", "issues": [],
                                            "content_sha256": content_digest(self.spec)}}
        write_json(self.project / "evidence.json", self.evidence)

    def tearDown(self):
        self.temporary.cleanup()

    def test_visual_changes_and_section_order_preserve_content_review(self):
        changed = copy.deepcopy(self.spec)
        changed["theme"]["accent"] = "#126a84"
        changed["layout"]["gap_mm"] = 12
        changed["sections"].reverse()
        changed["sections"][0].update(image_height_mm=80, hide_heading=True, highlight_rows=[1])
        changed["sections"][0]["tables"][0]["highlight_rows"] = []
        self.assertEqual(content_digest(changed), content_digest(self.spec))
        result = save_revision(self.project, changed, "Improve visual hierarchy")
        self.assertEqual(result["version"], 2)
        self.assertEqual(read_json(self.project / "evidence.json"), self.evidence)
        self.assertTrue(check_project(self.project)["content_pass"])

    def test_title_value_and_nested_table_caption_invalidate_review(self):
        changes = [lambda s: s.update(title="A different scientific claim"),
                   lambda s: s["sections"][1]["rows"][1].__setitem__(1, "0.95"),
                   lambda s: s["sections"][1]["tables"][0].update(caption="The training setting changes.")]
        for change in changes:
            with self.subTest(change=change):
                write_json(self.project / "poster.json", self.spec)
                write_json(self.project / "evidence.json", self.evidence)
                changed = copy.deepcopy(self.spec)
                change(changed)
                self.assertNotEqual(content_digest(changed), content_digest(self.spec))
                save_revision(self.project, changed, "Revise scientific content")
                self.assertEqual(read_json(self.project / "evidence.json")["content_review"]["status"], "pending")
                self.assertFalse(check_project(self.project)["content_pass"])

    def test_direct_json_content_edit_cannot_reuse_old_acceptance(self):
        self.assertTrue(check_project(self.project)["content_pass"])
        changed = copy.deepcopy(self.spec)
        changed["sections"][1]["tables"][0]["rows"][1][1] = "0.95"
        write_json(self.project / "poster.json", changed)
        report = check_project(self.project)
        self.assertFalse(report["content_pass"])
        self.assertFalse(report["review"]["content_accepted"])
        current = copy.deepcopy(self.evidence)
        current["content_review"]["content_sha256"] = content_digest(changed)
        write_json(self.project / "evidence.json", current)
        self.assertTrue(check_project(self.project)["content_pass"])

    def test_acceptance_without_content_digest_is_not_current(self):
        del self.evidence["content_review"]["content_sha256"]
        write_json(self.project / "evidence.json", self.evidence)
        self.assertFalse(check_project(self.project)["content_pass"])

    def test_approved_design_requires_explicit_reopen(self):
        frozen = copy.deepcopy(self.spec)
        frozen["status"] = "approved"
        frozen["approval"] = {"version": 1, "sha256": spec_digest(frozen)}
        write_json(self.project / "poster.json", frozen)
        changed = copy.deepcopy(frozen)
        changed["layout"]["gap_mm"] = 12
        with self.assertRaisesRegex(ValueError, "frozen"):
            save_revision(self.project, changed, "Unrequested change")
        self.assertFalse((self.project / "history").exists())
        self.assertEqual(read_json(self.project / "evidence.json"), self.evidence)
        reopened = reopen(self.project)
        reopened["layout"]["gap_mm"] = 12
        self.assertEqual(save_revision(self.project, reopened, "Requested revision")["version"], 2)

    def test_lock_changes_are_legal_and_unlocked_sections_can_change(self):
        changed = copy.deepcopy(self.spec)
        changed["locked_regions"] = ["method"]
        saved = save_revision(self.project, changed, "Preserve method")
        saved["sections"][1]["image_height_mm"] = 80
        self.assertEqual(save_revision(self.project, saved, "Adjust unlocked results")["version"], 3)
        saved = load_spec(self.project)
        saved["canvas"]["png_width"] = 7000
        self.assertEqual(save_revision(self.project, saved, "Increase export pixels")["version"], 4)
        saved = load_spec(self.project)
        saved["locked_regions"] = []
        self.assertEqual(save_revision(self.project, saved, "Unlock method")["locked_regions"], [])

    def test_locked_section_and_global_styles_are_protected(self):
        locked = copy.deepcopy(self.spec)
        locked["locked_regions"] = ["method"]
        write_json(self.project / "poster.json", locked)
        for change in [lambda s: s["sections"][0].update(image_height_mm=80),
                       lambda s: s["sections"][0]["paragraphs"].append("Extra statement"),
                       lambda s: s["layout"].update(gap_mm=12),
                       lambda s: s["sections"].reverse()]:
            candidate = copy.deepcopy(locked)
            change(candidate)
            with self.assertRaisesRegex(ValueError, "locked"):
                save_revision(self.project, candidate, "Affected preserved region")
        self.assertEqual(load_spec(self.project), locked)
        self.assertFalse((self.project / "history").exists())

    def test_header_lock_allows_other_region_edits_and_noop_styles(self):
        locked = copy.deepcopy(self.spec)
        locked["locked_regions"] = ["header"]
        write_json(self.project / "poster.json", locked)
        for key, value in [("title", "New title"), ("authors", "New author"), ("branding", {"logo": "assets/new.svg"})]:
            changed = copy.deepcopy(locked)
            changed[key] = value
            with self.assertRaisesRegex(ValueError, "header is locked"):
                save_revision(self.project, changed, "Changed header")
        saved = apply_visual_patch(self.project, {"layout": {"gap_mm": 10},
                                                  "sections": [{"id": "results", "hide_heading": True}],
                                                  "section_order": ["results", "method"]}, "Rearrange results")
        self.assertEqual(saved["version"], 2)
        self.assertEqual(saved["title"], self.spec["title"])
        self.assertTrue(check_project(self.project)["content_pass"])


if __name__ == "__main__":
    unittest.main()
