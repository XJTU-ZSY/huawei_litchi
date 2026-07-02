import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.run_ai_task import build_command, choose_provider, run_ai_task


class AiTaskRunnerTest(unittest.TestCase):
    def test_choose_provider_prefers_opencode(self):
        with patch("tools.run_ai_task.shutil.which", side_effect=lambda name: f"{name}.exe"):
            self.assertEqual(choose_provider("auto"), "opencode")

    def test_choose_provider_falls_back_to_codex(self):
        with patch("tools.run_ai_task.shutil.which", side_effect=lambda name: "codex.exe" if name == "codex" else None):
            self.assertEqual(choose_provider("auto"), "codex")

    def test_choose_provider_reports_missing_requested_provider(self):
        with patch("tools.run_ai_task.shutil.which", return_value=None):
            self.assertIsNone(choose_provider("opencode"))

    def test_build_codex_command_reads_prompt_from_stdin(self):
        command = build_command("codex", Path("task.prompt.md"), Path("repo"))

        self.assertEqual(command[:4], ["codex", "--ask-for-approval", "never", "exec"])
        self.assertIn("workspace-write", command)
        self.assertEqual(command[-1], "-")

    def test_run_ai_task_uses_stdin_for_codex(self):
        completed = subprocess.CompletedProcess(args=["codex"], returncode=0, stdout="ok", stderr="")
        with patch("tools.run_ai_task.choose_provider", return_value="codex"), patch.object(
            Path, "read_text", return_value="prompt text"
        ), patch("tools.run_ai_task.subprocess.run", return_value=completed) as run:
            result = run_ai_task(Path("task.prompt.md"), cwd=Path("repo"))

        self.assertEqual(result.returncode, 0)
        self.assertEqual(run.call_args.kwargs["input"], "prompt text")

    def test_run_ai_task_reports_missing_cli(self):
        with patch("tools.run_ai_task.choose_provider", return_value=None):
            result = run_ai_task(Path("task.prompt.md"), provider="auto")

        self.assertEqual(result.returncode, 127)
        self.assertIn("No AI CLI found", result.stderr)


if __name__ == "__main__":
    unittest.main()
