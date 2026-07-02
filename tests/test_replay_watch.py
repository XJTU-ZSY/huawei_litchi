import io
import unittest
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from litchi_bot.replay_watch import (
    ReplayCandidate,
    build_replay_report,
    build_requirement_cards,
    build_skill_handoff_prompt,
    create_done_files_from_latest_manifest,
    discover_replays,
    done_file_names_from_manifest_data,
    find_latest_manifest,
    is_stable,
    resolve_done_file_path,
)
from tools.watch_replays import format_stage_line, print_stage


class FakeStat:
    def __init__(self, size=10, mtime_ns=1):
        self.st_size = size
        self.st_mtime_ns = mtime_ns


class FakePath:
    def __init__(self, name, *, size=10, mtime_ns=1, file=True, text=""):
        self.name = name
        self._stat = FakeStat(size, mtime_ns)
        self._file = file
        self._text = text

    @property
    def suffix(self):
        return Path(self.name).suffix

    def is_file(self):
        return self._file

    def stat(self):
        return self._stat

    def read_text(self, encoding=None):
        return self._text

    def __lt__(self, other):
        return self.name < other.name


class FakeFolder:
    def __init__(self, paths=None, manifests=None):
        self.paths = paths or []
        self.manifests = manifests or []
        self.glob_pattern = None

    def exists(self):
        return True

    def rglob(self, pattern):
        return self.paths

    def glob(self, pattern):
        self.glob_pattern = pattern
        return self.manifests


class ReplayWatchTest(unittest.TestCase):
    def test_builds_p0_card_for_rejected_actions(self):
        summary = {
            "messageCount": 3,
            "rejectedCount": 1,
            "invalidCount": 0,
            "scores": {},
            "deliveries": {},
            "windowCards": {},
            "finalPlayers": {},
            "latestPlayers": {},
        }

        cards = build_requirement_cards(Path("match.json"), summary, player_id=1001)

        self.assertEqual(cards[0].priority, "P0")
        self.assertIn("拒绝/非法动作", cards[0].title)

    def test_builds_task90_card_when_task_score_is_low(self):
        summary = {
            "messageCount": 3,
            "rejectedCount": 0,
            "invalidCount": 0,
            "scores": {"1001": 120},
            "deliveries": {"1001": {"round": 500}},
            "windowCards": {},
            "finalPlayers": {"1001": {"playerId": 1001, "delivered": True, "taskScore": 60}},
            "latestPlayers": {},
        }

        cards = build_requirement_cards(Path("match.json"), summary, player_id=1001)

        self.assertTrue(any(card.priority == "P1" and "90" in card.title for card in cards))

    def test_report_uses_skill_report_sections(self):
        summary = {
            "messageCount": 1,
            "rejectedCount": 0,
            "invalidCount": 0,
            "scores": {},
            "deliveries": {},
            "windowCards": {"BING_ZHENG": 2},
            "finalPlayers": {},
            "latestPlayers": {},
            "eventCounts": {},
            "rejected": [],
            "invalid": [],
        }

        report = build_replay_report(Path("match.json"), summary, player_id=None)

        for heading in ("Outcome", "Hard Bugs", "Strategy Losses", "Opponent Lessons", "Recommended Cards", "Regression Checks"):
            self.assertIn(f"## {heading}", report)

    def test_stability_check(self):
        candidate = ReplayCandidate(Path("match.json"), size=10, mtime_ns=1_000_000_000)

        self.assertFalse(is_stable(candidate, stable_seconds=5, now=3))
        self.assertTrue(is_stable(candidate, stable_seconds=2, now=3))

    def test_discover_replays_ignores_manifest_files(self):
        folder = FakeFolder(
            [
                FakePath("match_001.jsonl"),
                FakePath("match_001.manifest.json"),
            ]
        )

        candidates = discover_replays(folder)

        self.assertEqual([candidate.path.name for candidate in candidates], ["match_001.jsonl"])

    def test_find_latest_manifest_scans_manifest_glob(self):
        older = FakePath("older.manifest.json", mtime_ns=10)
        newer = FakePath("newer.manifest.json", mtime_ns=20)
        folder = FakeFolder(manifests=[older, newer])

        manifest = find_latest_manifest(folder)

        self.assertEqual(manifest.name, "newer.manifest.json")
        self.assertEqual(folder.glob_pattern, "*.manifest.json")

    def test_done_file_names_from_manifest_data(self):
        data = {
            "clientA": {"doneFile": "clientA.done"},
            "clientB": {"doneFile": "clientB.done"},
        }

        self.assertEqual(done_file_names_from_manifest_data(data), ["clientA.done", "clientB.done"])
        self.assertEqual(done_file_names_from_manifest_data(data, client="clientA"), ["clientA.done"])

    def test_resolve_done_file_path_rejects_escape(self):
        self.assertEqual(resolve_done_file_path(Path("out"), "clientA.done"), Path("out") / "clientA.done")
        with self.assertRaisesRegex(ValueError, "inside replay_out_dir"):
            resolve_done_file_path(Path("out"), "..\\escape.done")
        with self.assertRaisesRegex(ValueError, "inside replay_out_dir"):
            resolve_done_file_path(Path("out"), ".")

    def test_resolve_done_file_path_allows_absolute_path_inside_replay_dir(self):
        replay_out_dir = Path("D:/workspace/replay_output")
        done_file = "D:/workspace/replay_output/match_001.client_a.done"

        self.assertEqual(resolve_done_file_path(replay_out_dir, done_file), Path(done_file))

    def test_resolve_done_file_path_rejects_absolute_path_outside_replay_dir(self):
        with self.assertRaisesRegex(ValueError, "inside replay_out_dir"):
            resolve_done_file_path(Path("D:/workspace/replay_output"), "D:/workspace/other/client_a.done")

    def test_create_done_files_from_latest_manifest(self):
        manifest = FakePath(
            "match_001.manifest.json",
            text='{"clientA": {"doneFile": "clientA.done"}, "clientB": {"doneFile": "clientB.done"}}',
        )
        with patch("litchi_bot.replay_watch.find_latest_manifest", return_value=manifest), patch.object(Path, "mkdir") as mkdir, patch.object(Path, "touch") as touch:
            paths = create_done_files_from_latest_manifest(Path("out"))

        self.assertEqual(paths, [Path("out") / "clientA.done", Path("out") / "clientB.done"])
        self.assertEqual(mkdir.call_count, 2)
        self.assertEqual(touch.call_count, 2)

    def test_skill_handoff_prompt_targets_replay_analyst_and_coach(self):
        prompt = build_skill_handoff_prompt(
            replay_path=Path("replays/match_001.json"),
            machine_report_path=Path(".replay_watch/reports/match_001.md"),
            process_log_path=Path(".replay_watch/process_logs/match_001.process.md"),
            player_id=1001,
        )

        self.assertIn("$litchi-replay-analyst", prompt)
        self.assertIn("$litchi-coach", prompt)
        self.assertIn("replays\\match_001.json", prompt.replace("/", "\\"))
        self.assertIn(".replay_watch\\reports\\match_001.md", prompt.replace("/", "\\"))
        self.assertIn(".replay_watch\\process_logs\\match_001.process.md", prompt.replace("/", "\\"))
        self.assertIn("quality gate", prompt)
        self.assertIn("git commit", prompt)
        self.assertIn("不直接改代码", prompt)


    def test_skill_handoff_prompt_can_request_implementation(self):
        prompt = build_skill_handoff_prompt(
            replay_path=Path("replays/match_001.json"),
            machine_report_path=Path(".replay_watch/reports/match_001.md"),
            process_log_path=Path(".replay_watch/process_logs/match_001.process.md"),
            player_id=1001,
            auto_implement=True,
        )

        self.assertIn("Auto-implement mode is ON", prompt)
        self.assertIn("$litchi-implementer", prompt)
        self.assertIn("$litchi-tester", prompt)
        self.assertIn("git commit", prompt)

    def test_stage_line_format(self):
        self.assertEqual(format_stage_line("idle"), "[STAGE] idle")
        self.assertEqual(
            format_stage_line("ai-command-start", "task.md"),
            "[STAGE] ai-command-start: task.md",
        )

    def test_print_stage_writes_to_stream(self):
        stream = io.StringIO()

        print_stage("report-written", "report.md", stream=stream)

        self.assertEqual(stream.getvalue(), "[STAGE] report-written: report.md\n")

    def test_watch_replays_help_exposes_process_log_dir(self):
        completed = subprocess.run(
            [sys.executable, "-B", "tools/watch_replays.py", "--help"],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("--process-log-dir", completed.stdout)
        self.assertIn("--auto-implement", completed.stdout)
        self.assertIn("--done-client", completed.stdout)
        self.assertIn("--skip-done-file", completed.stdout)

    def test_mark_replay_done_help(self):
        completed = subprocess.run(
            [sys.executable, "-B", "tools/mark_replay_done.py", "--help"],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("--client", completed.stdout)


if __name__ == "__main__":
    unittest.main()
