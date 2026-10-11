import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from poster_agent.doctor import doctor


class DoctorTests(unittest.TestCase):
    def test_actual_local_environment_and_configuration_without_secret_output(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {
                "OPENAI_API_KEY": "sk-test-secret-that-must-not-appear", "POSTER_MODEL": "test-model"}):
            report = doctor(directory)
        self.assertTrue(report["workspace"]["writable"])
        self.assertTrue(report["chromium"]["available"])
        self.assertTrue(report["chromium"]["launch_checked"])
        self.assertEqual(report["api"]["model"], "test-model")
        self.assertTrue(report["api"]["key_present"])
        self.assertFalse(report["api"]["network_verified"])
        self.assertNotIn("sk-test-secret-that-must-not-appear", json.dumps(report))
        self.assertTrue(report["packages"]["PyMuPDF"]["available"])

    def test_missing_dependency_and_workspace_have_actionable_repairs(self):
        import importlib
        original = importlib.import_module
        def missing_pymupdf(module):
            if module == "fitz":
                raise ImportError("fixture absence")
            return original(module)
        with tempfile.TemporaryDirectory() as directory, patch("poster_agent.doctor.importlib.import_module", side_effect=missing_pymupdf), \
                patch.dict("os.environ", {"OPENAI_API_KEY": "", "POSTER_MODEL": ""}):
            report = doctor(Path(directory) / "missing-workspace", check_browser=False)
        self.assertEqual(report["status"], "needs_setup")
        self.assertFalse(report["local_ready"])
        self.assertFalse(report["api_ready"])
        self.assertFalse(report["packages"]["PyMuPDF"]["available"])
        self.assertTrue(any('-m pip install "PyMuPDF"' in repair for repair in report["repair"]))
        self.assertTrue(any("workspace directory" in repair for repair in report["repair"]))
        self.assertTrue(any("OPENAI_API_KEY" in repair for repair in report["repair"]))

    def test_codex_entry_point_does_not_require_api_key(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {"OPENAI_API_KEY": "", "POSTER_MODEL": ""}), \
                patch("poster_agent.doctor.shutil.which", return_value="/fixture/poster-agent"):
            report = doctor(directory)
        self.assertEqual(report["status"], "local_ready")
        self.assertTrue(report["local_ready"])
        self.assertFalse(report["api_ready"])


if __name__ == "__main__":
    unittest.main()
