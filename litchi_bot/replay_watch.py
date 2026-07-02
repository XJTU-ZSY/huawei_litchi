from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

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
