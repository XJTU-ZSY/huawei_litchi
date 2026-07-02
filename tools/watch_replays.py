from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from litchi_bot.protocol import parse_player_id
from litchi_bot.replay_watch import (
    analyze_replay_file,
    append_cards_to_backlog,
    build_skill_handoff_prompt,
    build_requirement_cards,
    discover_replays,
    is_stable,
    load_state,
    run_ai_command,
    save_state,
    write_ai_task,
    write_report,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Continuously watch a replay folder and generate coach-ready reports")
    parser.add_argument("folder", help="Folder containing replay files")
    parser.add_argument("--player-id", help="Player ID to analyze as our bot")
    parser.add_argument("--interval", type=float, default=2.0, help="Polling interval in seconds")
    parser.add_argument("--stable-seconds", type=float, default=3.0, help="Wait until file has not changed for this long")
    parser.add_argument("--state", default=".replay_watch/state.json", help="Processed-file state path")
    parser.add_argument("--report-dir", default=".replay_watch/reports", help="Generated report output directory")
    parser.add_argument("--ai-task-dir", default=".replay_watch/ai_tasks", help="Generated skill handoff prompt directory")
    parser.add_argument("--no-ai-task", action="store_true", help="Do not generate skill handoff prompts")
    parser.add_argument(
        "--ai-command-template",
        help="Optional command to run for each generated prompt. Placeholders: {task}, {replay}, {report}",
    )
    parser.add_argument("--append-backlog", action="store_true", help="Append generated requirement cards to docs/backlog.md")
    parser.add_argument("--backlog", default="docs/backlog.md", help="Backlog path used with --append-backlog")
    parser.add_argument("--once", action="store_true", help="Scan once and exit; useful for tests or manual batches")
    parser.add_argument("--process-empty", action="store_true", help="Mark empty/unparsed replays as processed")
    args = parser.parse_args()

    folder = Path(args.folder)
    state_path = ROOT / args.state
    report_dir = ROOT / args.report_dir
    ai_task_dir = ROOT / args.ai_task_dir
    backlog_path = ROOT / args.backlog
    player_id = parse_player_id(args.player_id) if args.player_id else None

    print(f"watching {folder} every {args.interval}s; reports -> {report_dir}")
    while True:
        state = load_state(state_path)
        processed_any = False
        for candidate in discover_replays(folder):
            key = str(candidate.path.resolve())
            if state.get(key) == candidate.fingerprint:
                continue
            if not is_stable(candidate, args.stable_seconds):
                continue
            try:
                summary, report = analyze_replay_file(candidate.path, player_id)
            except Exception as exc:
                print(f"[ERROR] {candidate.path}: {exc}", file=sys.stderr)
                continue
            if summary["messageCount"] == 0 and not args.process_empty:
                print(f"[WAIT] {candidate.path}: no messages parsed yet", file=sys.stderr)
                continue
            report_path = write_report(report_dir, candidate.path, report)
            task_path = None
            if not args.no_ai_task:
                prompt = build_skill_handoff_prompt(candidate.path, report_path, player_id, args.append_backlog)
                task_path = write_ai_task(ai_task_dir, candidate.path, prompt)
            if args.ai_command_template and task_path is not None:
                completed = run_ai_command(args.ai_command_template, task_path, candidate.path, report_path)
                if completed.stdout.strip():
                    print(completed.stdout.strip())
                if completed.stderr.strip():
                    print(completed.stderr.strip(), file=sys.stderr)
                if completed.returncode != 0:
                    print(f"[ERROR] AI command failed with code {completed.returncode}: {task_path}", file=sys.stderr)
                    continue
            if args.append_backlog:
                append_cards_to_backlog(backlog_path, candidate.path, build_requirement_cards(candidate.path, summary, player_id))
            state[key] = candidate.fingerprint
            save_state(state_path, state)
            processed_any = True
            if task_path is not None:
                print(f"[OK] {candidate.path} -> {report_path}; AI task -> {task_path}")
            else:
                print(f"[OK] {candidate.path} -> {report_path}")
        if args.once:
            return 0
        if not processed_any:
            print("[idle] no new stable replay")
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
