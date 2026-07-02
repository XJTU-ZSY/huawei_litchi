from __future__ import annotations

import argparse
import os
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ZIP = ROOT / "dist" / "litchi_bot.zip"
FORBIDDEN_ZIP_PREFIXES = ("docs/", "tests/", "tools/", ".codex/", ".git/", "dist/", "logs/")

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from litchi_bot.protocol import parse_player_id
from litchi_bot.replay import analyze_messages, load_messages


@dataclass(frozen=True)
class GateStep:
    name: str
    passed: bool
    detail: str = ""


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the pre-commit quality gate")
    parser.add_argument("--skip-tests", action="store_true", help="Skip unit tests")
    parser.add_argument("--skip-package", action="store_true", help="Skip package build and zip validation")
    parser.add_argument("--replay", action="append", default=[], help="Replay or JSONL log to check; can be repeated")
    parser.add_argument("--player-id", help="Player ID to filter replay hard-bug checks")
    parser.add_argument("--max-rejected", type=int, default=0, help="Maximum allowed rejected actions in checked replays")
    parser.add_argument("--max-invalid", type=int, default=0, help="Maximum allowed invalid actions in checked replays")
    args = parser.parse_args(argv)

    steps: list[GateStep] = [check_start_script(ROOT)]
    if not args.skip_tests:
        steps.append(run_command("unit tests", [sys.executable, "-B", "-m", "unittest"]))
    if not args.skip_package:
        steps.append(run_command("build package", [sys.executable, "-B", "tools/package.py"]))
        steps.append(check_submission_zip(DEFAULT_ZIP))

    player_id = parse_player_id(args.player_id) if args.player_id else None
    for replay_path in args.replay:
        steps.append(check_replay(Path(replay_path), player_id, args.max_rejected, args.max_invalid))

    for step in steps:
        status = "PASS" if step.passed else "FAIL"
        print(f"[{status}] {step.name}")
        if step.detail:
            print(step.detail)

    return 0 if all(step.passed for step in steps) else 1


def run_command(name: str, command: list[str]) -> GateStep:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(command, cwd=ROOT, env=env, text=True, capture_output=True)
    detail_parts = []
    if completed.stdout.strip():
        detail_parts.append(completed.stdout.strip())
    if completed.stderr.strip():
        detail_parts.append(completed.stderr.strip())
    return GateStep(name, completed.returncode == 0, "\n".join(detail_parts))


def check_start_script(root: Path) -> GateStep:
    path = root / "start.sh"
    if not path.exists():
        return GateStep("start.sh exists", False, "missing start.sh")
    text = path.read_text(encoding="utf-8", errors="replace")
    missing = [token for token in ("$1", "$2", "$3", "litchi_bot.main") if token not in text]
    if missing:
        return GateStep("start.sh contract", False, f"missing expected token(s): {', '.join(missing)}")
    return GateStep("start.sh contract", True)


def check_submission_zip(path: Path) -> GateStep:
    issues = validate_submission_zip(path)
    return GateStep("submission zip", not issues, "\n".join(f"- {issue}" for issue in issues))


def validate_submission_zip(path: Path) -> list[str]:
    if not path.exists():
        return [f"missing package: {path}"]
    issues: list[str] = []
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        name_set = set(names)
        if "start.sh" not in name_set:
            issues.append("zip root must contain start.sh")
        if not any(name.startswith("litchi_bot/") and name.endswith(".py") for name in names):
            issues.append("zip must contain litchi_bot Python sources")
        for name in names:
            if name.startswith(FORBIDDEN_ZIP_PREFIXES):
                issues.append(f"forbidden submission path: {name}")
            if "__pycache__" in name or name.endswith((".pyc", ".pyo")):
                issues.append(f"bytecode/cache file included: {name}")
            if name.count("/") == 0 and name not in {"start.sh"}:
                issues.append(f"unexpected file at zip root: {name}")
        if "start.sh" in name_set:
            mode = (archive.getinfo("start.sh").external_attr >> 16) & 0o777
            if mode and not (mode & 0o111):
                issues.append("start.sh is not executable in zip metadata")
    return issues


def check_replay(path: Path, player_id: int | str | None, max_rejected: int, max_invalid: int) -> GateStep:
    if not path.exists():
        return GateStep(f"replay {path}", False, "file does not exist")
    try:
        summary = analyze_messages(load_messages(path), player_id)
    except Exception as exc:
        return GateStep(f"replay {path}", False, f"failed to analyze replay: {exc}")
    issues = []
    if summary["rejectedCount"] > max_rejected:
        issues.append(f"rejected actions {summary['rejectedCount']} > {max_rejected}")
    if summary["invalidCount"] > max_invalid:
        issues.append(f"invalid actions {summary['invalidCount']} > {max_invalid}")
    detail = f"messages={summary['messageCount']} rejected={summary['rejectedCount']} invalid={summary['invalidCount']}"
    if issues:
        detail += "\n" + "\n".join(f"- {issue}" for issue in issues)
    return GateStep(f"replay {path}", not issues, detail)


if __name__ == "__main__":
    raise SystemExit(main())
