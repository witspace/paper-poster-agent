"""CLI routing checks protect inputs and make API use explicit."""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from poster_agent.cli import main


class CliTests(unittest.TestCase):
    def invoke(self, args):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return main([str(value) for value in args])

    def test_run_requires_explicit_api_before_initialization(self):
        with tempfile.TemporaryDirectory() as directory, patch("poster_agent.ingest.ingest") as ingest:
            self.assertEqual(self.invoke(["run", directory]), 1)
            ingest.assert_not_called()

    def test_resume_preserves_initialized_paper(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "source").mkdir()
            (root / "source/paper.pdf").write_bytes(b"fixture")
            with patch("poster_agent.pipeline.run_pipeline", return_value={"status": "awaiting_human_review"}) as pipeline, patch("poster_agent.ingest.ingest") as ingest:
                self.assertEqual(self.invoke(["run", root, "--api", "--resume", "--max-rounds", "1"]), 0)
                pipeline.assert_called_once_with(root, True, 1)
                ingest.assert_not_called()

    def test_existing_project_rejects_new_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "source").mkdir()
            (root / "source/paper.pdf").write_bytes(b"fixture")
            with patch("poster_agent.pipeline.run_pipeline") as pipeline:
                self.assertEqual(self.invoke(["run", root, "--api", "--resume", "--paper", "different.pdf"]), 1)
                pipeline.assert_not_called()

    def test_approve_checks_actual_files_before_and_after_approval(self):
        with patch("poster_agent.render.check_project", side_effect=[{}, {"print_ready": True}]) as check, patch("poster_agent.cli.approve") as approve:
            self.assertEqual(self.invoke(["approve", "fixture"]), 0)
            self.assertEqual(check.call_count, 2)
            approve.assert_called_once_with(Path("fixture"))

    def test_diagnostics_and_demo_are_local_commands(self):
        with patch("poster_agent.doctor.doctor", return_value={"local_ready": True}) as doctor:
            self.assertEqual(self.invoke(["doctor", "--skip-browser"]), 0)
            doctor.assert_called_once_with(None, False)
        with patch("poster_agent.demo.create_demo", return_value={"is_demo": True}) as demo:
            self.assertEqual(self.invoke(["demo", "public-demo"]), 0)
            demo.assert_called_once_with(Path("public-demo"), 6000)


if __name__ == "__main__":
    unittest.main()
