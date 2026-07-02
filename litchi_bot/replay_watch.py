from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .process_log import append_process_event, create_process_log
from .replay import analyze_messages, format_report, load_messages

DEFAULT_EXTENSIONS = {".json", ".jsonl", ".log", ".txt", ".replay"}


@dataclass(frozen=True)
class ReplayCandidate:
    path: Path
    size: int
    mtime_ns: int

    @property
    def fingerprint(self) -> str:
        return f"{self.size}:{self.mtime_ns}"


def discover_replays(folder: Path, extensions: set[str] | None = None) -> list[ReplayCandidate]:
    extensions = extensions or DEFAULT_EXTENSIONS
    if not folder.exists():
        return []
    candidates: list[ReplayCandidate] = []
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in extensions:
            continue
        stat = path.stat()
        candidates.append(ReplayCandidate(path=path, size=stat.st_size, mtime_ns=stat.st_mtime_ns))
    return candidates


def is_stable(candidate: ReplayCandidate, stable_seconds: float, now: float | None = None) -> bool:
    if stable_seconds <= 0:
        return True
    now = time.time() if now is None else now
    return now - (candidate.mtime_ns / 1_000_000_000) >= stable_seconds


def load_state(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def save_state(path: Path, state: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def analyze_replay_file(path: Path, player_id: int | str | None = None) -> tuple[dict[str, Any], str]:
    messages = load_messages(path)
    summary = analyze_messages(messages, player_id)
    report = build_replay_report(path, summary, player_id)
    return summary, report


def build_replay_report(path: Path, summary: dict[str, Any], player_id: int | str | None = None) -> str:
    cards = build_requirement_cards(path, summary, player_id)
    player_key = None if player_id is None else str(player_id)
    player = _player_summary(summary, player_key)
    lines = [
        f"# Replay Report: {path.name}",
        "",
        f"Replay: `{path}`",
        f"Player: `{player_id}`" if player_id is not None else "Player: all visible players",
        "",
        "## Outcome",
        "",
        f"- Messages: {summary['messageCount']}",
        f"- Scores: {summary.get('scores', {})}",
        f"- Delivery events: {summary.get('deliveries', {})}",
        f"- Player snapshot: {player}",
        "",
        "## Hard Bugs",
        "",
        *_hard_bug_lines(summary, player_key),
        "",
        "## Strategy Losses",
        "",
        *_strategy_loss_lines(summary, player_key),
        "",
        "## Opponent Lessons",
        "",
        *_opponent_lesson_lines(summary),
        "",
        "## Recommended Cards",
        "",
        *(card.to_markdown() for card in cards),
        "",
        "## Regression Checks",
        "",
        "- Add this replay to quality gate with `--replay` after fixing any P0 issue.",
        "- Keep `python -B tools/quality_gate.py` passing before merging strategy changes.",
        "",
        "## Raw Summary",
        "",
        "```text",
        format_report(summary),
        "```",
        "",
    ]
    return "\n".join(lines)


@dataclass(frozen=True)
class RequirementCard:
    title: str
    priority: str
    evidence: str
    expected_behavior: str
    forbidden_behavior: str
    implementation_owner: str
    validation: str
    status: str = "proposed"

    def to_markdown(self) -> str:
        return "\n".join(
            [
                f"### {self.title}",
                "",
                f"Priority: {self.priority}",
                "",
                f"Evidence: {self.evidence}",
                "",
                f"Expected behavior: {self.expected_behavior}",
                "",
                f"Forbidden behavior: {self.forbidden_behavior}",
                "",
                f"Implementation owner: {self.implementation_owner}",
                "",
                f"Validation: {self.validation}",
                "",
                f"Status: {self.status}",
                "",
            ]
        )


def build_requirement_cards(path: Path, summary: dict[str, Any], player_id: int | str | None = None) -> list[RequirementCard]:
    cards: list[RequirementCard] = []
    player_key = None if player_id is None else str(player_id)
    rejected = int(summary.get("rejectedCount") or 0)
    invalid = int(summary.get("invalidCount") or 0)
    player = _player_dict(summary, player_key)

    if rejected or invalid:
        cards.append(
            RequirementCard(
                title="修复回放中的拒绝/非法动作",
                priority="P0",
                evidence=f"{path}: rejected={rejected}, invalid={invalid}",
                expected_behavior="相同局面下客户端发出合法动作或空动作心跳。",
                forbidden_behavior="继续发送会产生 ACTION_REJECTED 或 INVALID_ACTION 的动作。",
                implementation_owner="$litchi-protocol-expert -> $litchi-architect -> $litchi-implementer",
                validation=f"python -B tools/quality_gate.py --replay {path} --player-id {player_id}",
            )
        )

    if player_key is not None and player and not _is_delivered(summary, player_key):
        cards.append(
            RequirementCard(
                title="补足未交付闭环",
                priority="P0",
                evidence=f"{path}: player {player_key} has no DELIVER_SUCCESS evidence",
                expected_behavior="进入 RUSH 后完成 S14 验核，并在 S15 满足条件时交付。",
                forbidden_behavior="在 S14/S15 附近长期等待、未验核交付、或交付前被其他目标拖走。",
                implementation_owner="$litchi-coach -> $litchi-architect -> $litchi-implementer",
                validation=f"python -B tools/quality_gate.py --replay {path} --player-id {player_id}",
            )
        )

    task_score = _task_score(player)
    if task_score is not None and task_score < 90:
        cards.append(
            RequirementCard(
                title="把普通任务基础分稳定推到 90",
                priority="P1",
                evidence=f"{path}: observed taskScore={task_score}",
                expected_behavior="在不破坏交付的前提下，优先规划最近可行任务直到任务基础分达到 90。",
                forbidden_behavior="只冲终点导致送达基础分和用时分被任务系数折扣。",
                implementation_owner="$litchi-coach -> $litchi-architect -> $litchi-implementer",
                validation="新增任务规划单测，并运行 python -B tools/quality_gate.py",
            )
        )

    if not cards:
        cards.append(
            RequirementCard(
                title="从无硬错误回放中提炼收益优化",
                priority="P1",
                evidence=f"{path}: no rejected/invalid actions found by watcher",
                expected_behavior="比较路线、资源、任务和窗口选择，提出一个可度量的收益优化。",
                forbidden_behavior="在没有回归验证的情况下扩大策略改动范围。",
                implementation_owner="$litchi-replay-analyst -> $litchi-coach",
                validation="用同一回放和 quality gate 验证无 P0 回归。",
            )
        )
    return cards


def write_report(report_dir: Path, replay_path: Path, report: str) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    output = report_dir / f"{_safe_name(replay_path.stem)}.md"
    output.write_text(report, encoding="utf-8")
    return output


def build_skill_handoff_prompt(
    replay_path: Path,
    machine_report_path: Path,
    process_log_path: Path,
    player_id: int | str | None = None,
    append_backlog: bool = False,
) -> str:
    player_line = f"我方 playerId 是 `{player_id}`。" if player_id is not None else "请先从回放中识别我方 playerId；如果无法识别，明确说明。"
    backlog_instruction = (
        "请把最终需求卡追加到 `docs/backlog.md`。"
        if append_backlog
        else "请先输出需求卡草案，不要直接修改 `docs/backlog.md`，除非用户确认。"
    )
    return "\n".join(
        [
            "使用 $litchi-replay-analyst 和 $litchi-coach 处理新回放。",
            "",
            "技能路径：",
            "- `$litchi-replay-analyst`: `.codex/skills/litchi-replay-analyst/SKILL.md`",
            "- `$litchi-coach`: `.codex/skills/litchi-coach/SKILL.md`",
            "",
            "输入：",
            f"- 原始回放：`{replay_path}`",
            f"- 机器预分析报告：`{machine_report_path}`",
            f"- 本轮流程日志：`{process_log_path}`",
            f"- {player_line}",
            "",
            "请按以下顺序执行：",
            "1. 先使用 `$litchi-replay-analyst`，读取原始回放和机器预分析报告。",
            "2. 不要只复述机器报告；需要用 AI 判断补充：卡住原因、策略失误、对手优秀策略、窗口/路线/任务模式。",
            "3. 再交给 `$litchi-coach`，按 P0/P1/P2 排优先级。",
            "4. 生成 1-3 张可执行需求卡，每张卡必须包含 Evidence、Expected behavior、Forbidden behavior、Implementation owner、Validation。",
            "5. P0 问题优先于胜率优化；没有 P0 问题时，再选择最高预期收益的 P1/P2 卡。",
            "6. 把 replay analyst 分析过程、coach 排序理由、需求卡内容追加到本轮流程日志。",
            f"7. {backlog_instruction}",
            "",
            "输出格式：",
            "```text",
            "Replay:",
            "Outcome:",
            "Hard bugs:",
            "Strategy losses:",
            "Opponent lessons:",
            "Recommended cards:",
            "Regression checks:",
            "```",
            "",
            "限制：",
            "- 本轮只做分析和需求卡，不直接改代码，除非用户明确要求实现。",
            "- 如果后续用户要求实现代码，必须继续把架构决策、代码变更、测试结果、quality gate 结果和 git commit 写入同一个流程日志。",
            "- 如果证据不足，写明缺失字段或需要补充的回放/日志。",
            "- 需求卡的 Validation 优先使用 `python -B tools/quality_gate.py` 和具体回放回归。",
            "",
        ]
    )


def write_ai_task(task_dir: Path, replay_path: Path, prompt: str) -> Path:
    task_dir.mkdir(parents=True, exist_ok=True)
    output = task_dir / f"{_safe_name(replay_path.stem)}.prompt.md"
    output.write_text(prompt, encoding="utf-8")
    return output


def process_log_path_for(log_dir: Path, replay_path: Path) -> Path:
    return log_dir / f"{_safe_name(replay_path.stem)}.process.md"


def start_replay_process_log(log_dir: Path, replay_path: Path, player_id: int | str | None = None) -> Path:
    path = process_log_path_for(log_dir, replay_path)
    create_process_log(
        path,
        f"Replay Iteration: {replay_path.name}",
        {
            "replay": replay_path,
            "player_id": player_id if player_id is not None else "unknown",
        },
    )
    append_process_event(path, "Replay detected", f"Watcher detected stable replay `{replay_path}`.")
    return path


def run_ai_command(command_template: str, task_path: Path, replay_path: Path, report_path: Path) -> subprocess.CompletedProcess[str]:
    command = command_template.format(
        task=str(task_path),
        replay=str(replay_path),
        report=str(report_path),
    )
    return subprocess.run(command, shell=True, text=True, capture_output=True)


def append_cards_to_backlog(backlog_path: Path, replay_path: Path, cards: Iterable[RequirementCard]) -> None:
    backlog_path.parent.mkdir(parents=True, exist_ok=True)
    text = ["", f"## 回放生成需求：{replay_path.name}", ""]
    for card in cards:
        text.append(card.to_markdown())
    with backlog_path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(text))


def _hard_bug_lines(summary: dict[str, Any], player_key: str | None) -> list[str]:
    lines = []
    rejected = int(summary.get("rejectedCount") or 0)
    invalid = int(summary.get("invalidCount") or 0)
    if rejected:
        lines.append(f"- ACTION_REJECTED count: {rejected}")
    if invalid:
        lines.append(f"- INVALID_ACTION count: {invalid}")
    if player_key is not None and _player_dict(summary, player_key) and not _is_delivered(summary, player_key):
        lines.append(f"- Player {player_key} has no confirmed delivery.")
    return lines or ["- No hard bug detected by automated scan."]


def _strategy_loss_lines(summary: dict[str, Any], player_key: str | None) -> list[str]:
    player = _player_dict(summary, player_key)
    task_score = _task_score(player)
    lines = []
    if task_score is not None and task_score < 90:
        lines.append(f"- Task score below 90 threshold: {task_score}")
    scores = summary.get("scores") or {}
    if scores:
        lines.append(f"- Final score table: {scores}")
    return lines or ["- No automated strategy loss detected; inspect route/task/resource choices manually."]


def _opponent_lesson_lines(summary: dict[str, Any]) -> list[str]:
    cards = summary.get("windowCards") or {}
    if cards:
        return [f"- Observed window card distribution: {cards}"]
    return ["- No window-card pattern detected by automated scan."]


def _player_dict(summary: dict[str, Any], player_key: str | None) -> dict[str, Any]:
    if player_key is None:
        return {}
    return (summary.get("finalPlayers") or {}).get(player_key) or (summary.get("latestPlayers") or {}).get(player_key) or {}


def _player_summary(summary: dict[str, Any], player_key: str | None) -> dict[str, Any]:
    player = _player_dict(summary, player_key)
    if not player:
        return {}
    return {
        "playerId": player.get("playerId"),
        "teamId": player.get("teamId"),
        "state": player.get("state"),
        "delivered": player.get("delivered"),
        "totalScore": player.get("totalScore"),
        "taskScore": player.get("taskScore"),
        "penaltyScore": player.get("penaltyScore"),
        "freshness": player.get("freshness"),
        "goodFruit": player.get("goodFruit"),
    }


def _is_delivered(summary: dict[str, Any], player_key: str) -> bool:
    if player_key in (summary.get("deliveries") or {}):
        return True
    player = _player_dict(summary, player_key)
    return bool(player.get("delivered"))


def _task_score(player: dict[str, Any]) -> int | None:
    if not player:
        return None
    score = player.get("taskScore")
    if score is None:
        score_detail = player.get("scoreDetail") or {}
        score = score_detail.get("tasks")
    if score is None:
        return None
    try:
        return int(score)
    except (TypeError, ValueError):
        return None


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value) or "replay"
