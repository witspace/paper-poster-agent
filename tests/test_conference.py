"""Conference semantics are checked deterministically with mocked official text."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from poster_agent.conference import applicable_requirements, import_profile, validate_research
from poster_agent.project import read_json, write_json


class ConferenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.project = Path(self.temporary.name)
        self.identity = {"name": "Fixture Conference", "year": 2026, "track": "Main"}
        write_json(self.project / "conference.json", {"identity": self.identity})

    def profile(self, quote="Posters must use portrait A0 format.", width=841, height=1189, orientation="portrait"):
        return {"identity": self.identity, "official_domains": ["example.org"],
                "sources": [{"url": "https://example.org/2026/posters", "quote": quote, "category": "mandatory_poster", "year": 2026, "track": "all_tracks", "scope": "all_tracks"}],
                "requirements": {"width_mm": width, "height_mm": height, "orientation": orientation},
                "requirement_sources": {"width_mm": [0], "height_mm": [0], "orientation": [0]}, "unresolved": []}

    def validate(self, profile, texts=None):
        texts = texts or {source["url"]: "Fixture Conference 2026 " + source["quote"] for source in profile["sources"]}
        with patch("poster_agent.conference.fetch_source", side_effect=lambda url, domains: texts[url]):
            return validate_research(self.project, profile)

    def assert_unconfirmed(self, profile, field, texts=None):
        with self.assertRaisesRegex(ValueError, "unconfirmed"):
            self.validate(profile, texts)
        saved = read_json(self.project / "conference.json")
        self.assertTrue(any(message.startswith(field + ":") for message in saved["unresolved"]), saved)
        return saved

    def test_named_paper_sizes_and_explicit_mm_cm_inches(self):
        for quote, width, height, orientation in (
            ("Posters must use portrait A0 format.", 841, 1189, "portrait"),
            ("Posters must use landscape A1 format.", 841, 594, "landscape"),
            ("Posters must use portrait A2 format.", 420, 594, "portrait"),
            ("Portrait posters must be 841 x 1189 mm.", 841, 1189, "portrait"),
            ("Portrait posters must be 84.1 × 118.9 cm.", 841, 1189, "portrait"),
            ("Portrait posters must be 36 x 48 inches.", 914.4, 1219.2, "portrait"),
            ("Portrait A0 posters are 33.11 x 46.81 inches.", 841, 1189, "portrait"),
            ("Portrait poster width: 841 mm, height: 1189 mm.", 841, 1189, "portrait"),
        ):
            with self.subTest(quote=quote):
                profile = self.validate(self.profile(quote, width, height, orientation))
                self.assertEqual(profile["unresolved"], [])
                self.assertEqual(profile["sources"][0]["verification"], "fetched_quote_matched")

    def test_quote_match_does_not_certify_wrong_numeric_interpretation(self):
        saved = self.assert_unconfirmed(self.profile(width=900, height=1200), "width_mm")
        self.assertEqual(saved["sources"][0]["verification"], "fetched_quote_matched")
        self.assertTrue(any(message.startswith("height_mm:") for message in saved["unresolved"]))
        self.assert_unconfirmed(self.profile("Poster presentation will be available on site."), "width_mm")

    def test_orientation_and_explicit_size_conflicts_are_unresolved(self):
        for profile in (self.profile(width=1189, height=841, orientation="landscape"),
                        self.profile("Landscape A0 posters are required."),
                        self.profile("Portrait A0 posters must be 1189 x 841 mm."),
                        self.profile("Use portrait A0 or A1 posters.")):
            with self.subTest(profile=profile):
                self.assert_unconfirmed(profile, "width_mm")
        self.assert_unconfirmed(self.profile("A0 posters are required."), "orientation")

    def test_maximum_size_and_either_orientation_are_explicit_choices(self):
        maximum = self.profile("Use portrait posters up to A0 size.")
        self.assert_unconfirmed(maximum, "width_mm")
        maximum["requirements"]["dimension_policy"] = "maximum"
        maximum["requirement_sources"]["dimension_policy"] = [0]
        self.assertEqual(self.validate(maximum)["unresolved"], [])
        either = self.profile("Use A0 posters in either orientation: portrait or landscape.", orientation="either")
        self.assertEqual(self.validate(either)["unresolved"], [])

    def test_two_allowed_orientations_cannot_be_spliced_into_square_dimensions(self):
        quote = "Use A0 posters in either portrait or landscape orientation."
        for width, height in ((841, 1189), (1189, 841)):
            self.assertEqual(self.validate(self.profile(quote, width, height, "either"))["unresolved"], [])
        for width, height in ((841, 841), (1189, 1189)):
            with self.subTest(width=width, height=height):
                saved = self.assert_unconfirmed(self.profile(quote, width, height, "either"), "width_mm")
                self.assertTrue(any(message.startswith("height_mm:") for message in saved["unresolved"]))

    def test_source_year_track_category_scope_and_exact_excerpt(self):
        for field, value in (("year", 2025), ("track", "Workshop"), ("category", "optional_printing"), ("scope", "Workshop")):
            profile = self.profile()
            profile["sources"][0][field] = value
            with self.subTest(field=field):
                self.assert_unconfirmed(profile, "width_mm")
        profile = self.profile()
        self.assert_unconfirmed(profile, "width_mm", {profile["sources"][0]["url"]: "Fixture Conference 2026. A different quote."})
        profile = self.profile("Workshop posters must use portrait A0 format.")
        self.assert_unconfirmed(profile, "width_mm")
        profile = self.profile("For the 2025 conference, posters must use portrait A0 format.")
        self.assert_unconfirmed(profile, "width_mm")
        profile = self.profile()
        self.assert_unconfirmed(profile, "width_mm", {profile["sources"][0]["url"]: "Fixture Conference 2025 " + profile["sources"][0]["quote"]})

    def test_optional_service_cannot_be_relabelled_as_mandatory(self):
        profile = self.profile("The optional printing service requires portrait A0 posters.")
        self.assert_unconfirmed(profile, "width_mm")
        profile["sources"][0]["category"] = "optional_printing"
        self.assert_unconfirmed(profile, "width_mm")

    def service_profile(self):
        profile = self.profile()
        profile["sources"].append({"url": "https://example.org/2026/printing", "quote": "The printing service accepts portrait A0 PDF files named Poster_Track_PaperID.pdf.",
                                    "category": "optional_printing", "year": 2026, "track": "Main", "scope": "Main"})
        profile["printing_service"] = {"template": "Poster_{track}_{paper_id}.pdf", "requirements": {"width_mm": 841, "height_mm": 1189, "orientation": "portrait", "format": "PDF"},
                                       "requirement_sources": {"file_name": [1], "width_mm": [1], "height_mm": [1], "orientation": [1], "format": [1]},
                                       "unresolved": ["Supply paper_id when selecting the optional service"]}
        return profile

    def test_boolean_and_malformed_mapping_indices_never_count_as_evidence(self):
        for indices in ([True], [False], [-1], [1], "0", 0, [], [0.0]):
            profile = self.profile()
            profile["requirement_sources"]["width_mm"] = indices
            with self.subTest(indices=indices):
                self.assert_unconfirmed(profile, "width_mm")
        profile = self.service_profile()
        profile["printing_service"]["requirement_sources"]["file_name"] = [True]
        validated = self.validate(profile)
        self.assertEqual(validated["unresolved"], [], "An optional service does not block ordinary poster rules")
        self.assertTrue(any(message.startswith("file_name:") for message in validated["printing_service"]["unresolved_rules"]))

    def test_service_template_needs_file_name_mapping_and_failed_rules_are_separate(self):
        profile = self.service_profile()
        validated = self.validate(profile)
        self.assertEqual(validated["printing_service"]["unresolved_rules"], [])
        self.assertIn("Supply paper_id", validated["printing_service"]["unresolved"][0])
        profile["printing_service"]["requirement_sources"].pop("file_name")
        validated = self.validate(profile)
        self.assertTrue(any(message.startswith("file_name:") for message in validated["printing_service"]["unresolved_rules"]))
        self.assertEqual(validated["unresolved"], [])
        profile = self.service_profile()
        profile["printing_service"]["requirements"]["width_mm"] = 900
        validated = self.validate(profile)
        self.assertTrue(any(message.startswith("width_mm:") for message in validated["printing_service"]["unresolved_rules"]))
        self.assertTrue(any(message.startswith("width_mm:") for message in validated["printing_service"]["unresolved"]))

    def test_applicable_rules_keep_true_mandatory_filename_and_isolate_legacy_service(self):
        profile = self.service_profile()
        profile["requirements"]["file_name"] = "Mandatory.pdf"
        legacy = applicable_requirements(profile)
        self.assertNotIn("file_name", legacy)
        self.assertEqual(applicable_requirements(profile, printing_service=True)["file_name"], "Poster_{track}_{paper_id}.pdf")
        profile["requirement_sources"]["file_name"] = [0]
        self.assertEqual(applicable_requirements(profile)["file_name"], "Mandatory.pdf")
        del profile["printing_service"]
        del profile["requirement_sources"]["file_name"]
        self.assertEqual(applicable_requirements(profile)["file_name"], "Mandatory.pdf")

    def test_explicit_checked_import_resolves_human_interpreted_size_without_network(self):
        profile = self.profile("Print the poster to fit the approved display board.")
        self.assert_unconfirmed(profile, "width_mm")
        file = self.project / "checked-profile.json"
        write_json(file, profile)
        with patch("poster_agent.conference.fetch_source", side_effect=AssertionError("Explicit import must not fetch")):
            imported = import_profile(self.project, file)
        self.assertEqual(imported["verification_mode"], "explicit_local_profile_import")
        self.assertEqual(imported["sources"][0]["verification"], "explicitly_imported_checked_profile")
        self.assertEqual(imported["unresolved"], [])

    def test_import_still_requires_correct_identity_scope_and_rule_mappings(self):
        for mutation in (lambda p: p["identity"].update(year=2025),
                         lambda p: p["sources"][0].update(track="Workshop"),
                         lambda p: p["sources"][0].update(category="optional_printing"),
                         lambda p: p["requirement_sources"].update(width_mm=[True])):
            profile = copy.deepcopy(self.profile())
            mutation(profile)
            file = self.project / "invalid-profile.json"
            write_json(file, profile)
            with self.assertRaises(ValueError):
                import_profile(self.project, file)


if __name__ == "__main__":
    unittest.main()
