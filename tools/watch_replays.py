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
    analysis_doc_path_for,
    append_cards_to_backlog,
    build_skill_handoff_prompt,
    create_done_files_from_latest_manifest,
    build_requirement_cards,
    discover_replays,
    is_stable,
    load_state,
    run_ai_command,
    save_state,
    start_replay_process_log,
    write_ai_task,
    write_report,
)
from litchi_bot.process_log import append_process_event


def format_stage_line(stage: str, detail: str = "") -> str:
    return f"[STAGE] {stage}: {detail}" if detail else f"[STAGE] {stage}"


def print_stage(stage: str, detail: str = "", *, stream=None) -> None:
    if stream is None:
        stream = sys.stdout
    print(format_stage_line(stage, detail), file=stream, flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Continuously watch a replay folder and generate coach-ready reports")
    parser.add_argument("folder", help="Folder containing replay files")
    parser.add_argument("--player-id", help="Player ID to analyze as our bot")
    parser.add_argument("--interval", type=float, default=2.0, help="Polling interval in seconds")
    parser.add_argument("--stable-seconds", type=float, default=3.0, help="Wait until file has not changed for this long")
    parser.add_argument("--state", default=".replay_watch/state.json", help="Processed-file state path")
    parser.add_argument("--report-dir", default=".replay_watch/reports", help="Generated report output directory")
    parser.add_argument("--analysis-doc-dir", default=".replay_watch/analysis_docs", help="AI-authored per-replay analysis document directory")
    parser.add_argument("--ai-task-dir", default=".replay_watch/ai_tasks", help="Generated skill handoff prompt directory")
    parser.add_argument("--process-log-dir", default=".replay_watch/process_logs", help="Per-replay process log directory")
    parser.add_argument("--no-ai-task", action="store_true", help="Do not generate skill handoff prompts")
    parser.add_argument(
        "--ai-command-template",
        help="Optional command to run for each generated prompt. Placeholders: {task}, {replay}, {report}, {analysis_doc}",
    )
    parser.add_argument("--append-backlog", action="store_true", help="Append generated requirement cards to docs/backlog.md")
    parser.add_argument("--backlog", default="docs/backlog.md", help="Backlog path used with --append-backlog")
    parser.add_argument("--auto-implement", action="store_true", help="Ask the AI handoff to continue from cards into implementation, tests, quality gate, and git commit")
    parser.add_argument("--done-client", choices=("clientA", "clientB"), help="Only create the manifest doneFile for this client; default creates all declared doneFiles")
    parser.add_argument("--skip-done-file", action="store_true", help="Do not create manifest doneFile markers after a successful AI command")
    parser.add_argument("--once", action="store_true", help="Scan once and exit; useful for tests or manual batches")
    parser.add_argument("--process-empty", action="store_true", help="Mark empty/unparsed replays as processed")
    args = parser.parse_args()

    folder = Path(args.folder)
    state_path = ROOT / args.state
    report_dir = ROOT / args.report_dir
    analysis_doc_dir = ROOT / args.analysis_doc_dir
    ai_task_dir = ROOT / args.ai_task_dir
    process_log_dir = ROOT / args.process_log_dir
    backlog_path = ROOT / args.backlog
    player_id = parse_player_id(args.player_id) if args.player_id else None

    print_stage("watch-start", f"folder={folder}; interval={args.interval}s; reports={report_dir}")
    while True:
        state = load_state(state_path)
        processed_any = False
        for candidate in discover_replays(folder):
            key = str(candidate.path.resolve())
            if state.get(key) == candidate.fingerprint:
                continue
            if not is_stable(candidate, args.stable_seconds):
                print_stage("wait-stable", str(candidate.path))
                continue
            print_stage("replay-detected", str(candidate.path))
            try:
                print_stage("machine-analysis-start", str(candidate.path))
                summary, report = analyze_replay_file(candidate.path, player_id)
            except Exception as exc:
                print(f"[ERROR] {candidate.path}: {exc}", file=sys.stderr)
                continue
            if summary["messageCount"] == 0 and not args.process_empty:
                print(f"[WAIT] {candidate.path}: no messages parsed yet", file=sys.stderr)
                continue
            print_stage(
                "machine-analysis-complete",
                f"messages={summary['messageCount']}; rejected={summary['rejectedCount']}; invalid={summary['invalidCount']}",
            )
            process_log_path = start_replay_process_log(process_log_dir, candidate.path, player_id)
            print_stage("process-log", str(process_log_path))
            report_path = write_report(report_dir, candidate.path, report)
            print_stage("report-written", str(report_path))
            analysis_doc_path = analysis_doc_path_for(analysis_doc_dir, candidate.path)
            analysis_doc_path.parent.mkdir(parents=True, exist_ok=True)
            print_stage("analysis-doc", str(analysis_doc_path))
            append_process_event(
                process_log_path,
                "Machine replay analysis",
                f"Generated machine report `{report_path}`.\n\nAI replay analysis document must be saved to `{analysis_doc_path}`.\n\nSummary: messages={summary['messageCount']}, rejected={summary['rejectedCount']}, invalid={summary['invalidCount']}.",
            )
            task_path = None
            if not args.no_ai_task:
                print_stage("ai-handoff-build", str(candidate.path))
                prompt = build_skill_handoff_prompt(
                    candidate.path,
                    report_path,
                    process_log_path,
                    player_id,
                    args.append_backlog,
                    args.auto_implement,
                    analysis_doc_path=analysis_doc_path,
                )
                task_path = write_ai_task(ai_task_dir, candidate.path, prompt)
                print_stage("ai-task-written", str(task_path))
                append_process_event(process_log_path, "AI handoff prompt", f"Generated skill handoff prompt `{task_path}`.")
            if args.ai_command_template and task_path is not None:
                print_stage("ai-command-start", str(task_path))
                completed = run_ai_command(args.ai_command_template, task_path, candidate.path, report_path, analysis_doc_path)
                if completed.stdout.strip():
                    print(completed.stdout.strip())
                if completed.stderr.strip():
                    print(completed.stderr.strip(), file=sys.stderr)
                if completed.returncode != 0:
                    append_process_event(process_log_path, "AI command failed", f"Command exited with `{completed.returncode}` for `{task_path}`.")
                    print(f"[ERROR] AI command failed with code {completed.returncode}: {task_path}", file=sys.stderr)
                    print_stage("ai-command-failed", f"code={completed.returncode}; task={task_path}", stream=sys.stderr)
                    continue
                print_stage("ai-command-complete", str(task_path))
                append_process_event(process_log_path, "AI command completed", f"Command completed for `{task_path}`.")
                if not args.skip_done_file:
                    try:
                        print_stage("done-file-start", str(folder))
                        done_paths = create_done_files_from_latest_manifest(folder, args.done_client)
                    except Exception as exc:
                        append_process_event(process_log_path, "Done file failed", f"Could not create doneFile marker from latest manifest in `{folder}`: {exc}")
                        print(f"[ERROR] failed to create doneFile marker from latest manifest: {exc}", file=sys.stderr)
                        print_stage("done-file-failed", str(exc), stream=sys.stderr)
                        continue
                    if done_paths:
                        print_stage("done-file-created", ", ".join(str(path) for path in done_paths))
                        append_process_event(process_log_path, "Done file created", "Created doneFile marker(s): " + ", ".join(f"`{path}`" for path in done_paths))
                    else:
                        append_process_event(process_log_path, "Done file missing", f"No latest `*.manifest.json` or doneFile entry found in `{folder}`.")
                        print(f"[ERROR] no latest *.manifest.json or doneFile entry found in {folder}", file=sys.stderr)
                        print_stage("done-file-missing", str(folder), stream=sys.stderr)
                        continue
            if args.append_backlog:
                print_stage("backlog-append", str(backlog_path))
                append_cards_to_backlog(backlog_path, candidate.path, build_requirement_cards(candidate.path, summary, player_id))
                append_process_event(process_log_path, "Backlog append", f"Appended machine-generated cards to `{backlog_path}`.")
            state[key] = candidate.fingerprint
            save_state(state_path, state)
            print_stage("state-saved", str(state_path))
            append_process_event(process_log_path, "Watcher state saved", f"Updated processed state `{state_path}`.")
            processed_any = True
            if task_path is not None:
                print(f"[OK] {candidate.path} -> {report_path}; AI task -> {task_path}")
            else:
                print(f"[OK] {candidate.path} -> {report_path}")
            print_stage("replay-complete", str(candidate.path))
        if args.once:
            return 0
        if not processed_any:
            print_stage("idle", "no new stable replay")
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
