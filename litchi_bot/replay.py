from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from .framing import FrameDecoder, ProtocolError


def load_messages(path: str | Path) -> list[dict[str, Any]]:
    path = Path(path)
    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        return []
    messages = _try_json(text)
    if messages:
        return messages
    messages = _try_jsonl(text)
    if messages:
        return messages
    return _try_framed(raw)


def analyze_messages(messages: list[dict[str, Any]], player_id: int | str | None = None) -> dict[str, Any]:
    event_counts: Counter[str] = Counter()
    rejected: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    window_cards: Counter[str] = Counter()
    scores: dict[str, Any] = {}
    deliveries: dict[str, Any] = {}
    final_players: dict[str, Any] = {}
    latest_players: dict[str, Any] = {}

    for message in messages:
        name = message.get("msg_name")
        data = message.get("msg_data") or message
        if name == "over":
            for player in data.get("players") or []:
                player_key = str(player.get("playerId"))
                scores[player_key] = player.get("totalScore")
                final_players[player_key] = player
        for player in data.get("players") or []:
            if player.get("playerId") is not None:
                latest_players[str(player.get("playerId"))] = player
        for event in data.get("events") or []:
            event_type = str(event.get("type"))
            payload = event.get("payload") or {}
            event_counts[event_type] += 1
            if _matches_player(payload, player_id):
                if event_type == "ACTION_REJECTED":
                    rejected.append(event)
                elif event_type == "INVALID_ACTION":
                    invalid.append(event)
                elif event_type == "DELIVER_SUCCESS":
                    deliveries[str(payload.get("playerId"))] = {
                        "round": event.get("round"),
                        "goodFruit": payload.get("goodFruit"),
                        "freshness": payload.get("freshness"),
                    }
            if event_type == "WINDOW_CARD_REVEAL":
                for key in ("redCard", "blueCard"):
                    if payload.get(key):
                        window_cards[str(payload[key])] += 1

    return {
        "messageCount": len(messages),
        "eventCounts": dict(event_counts),
        "rejectedCount": len(rejected),
        "invalidCount": len(invalid),
        "rejected": rejected[:20],
        "invalid": invalid[:20],
        "windowCards": dict(window_cards),
        "scores": scores,
        "deliveries": deliveries,
        "finalPlayers": final_players,
        "latestPlayers": latest_players,
    }


def format_report(summary: dict[str, Any]) -> str:
    lines = [
        f"messages: {summary['messageCount']}",
        f"rejected actions: {summary['rejectedCount']}",
        f"invalid actions: {summary['invalidCount']}",
        f"scores: {summary['scores']}",
        f"deliveries: {summary['deliveries']}",
        f"window cards: {summary['windowCards']}",
    ]
    if summary["rejected"]:
        lines.append("first rejected events:")
        lines.extend(_format_event(event) for event in summary["rejected"][:5])
    if summary["invalid"]:
        lines.append("first invalid events:")
        lines.extend(_format_event(event) for event in summary["invalid"][:5])
    top_events = sorted(summary["eventCounts"].items(), key=lambda item: (-item[1], item[0]))[:12]
    lines.append(f"top events: {dict(top_events)}")
    return "\n".join(lines)


def _try_json(text: str) -> list[dict[str, Any]]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return []
    return list(_walk_messages(value))


def _try_jsonl(text: str) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            return []
        messages.extend(_walk_messages(value))
    return messages


def _try_framed(raw: bytes) -> list[dict[str, Any]]:
    decoder = FrameDecoder()
    try:
        return decoder.feed(raw)
    except ProtocolError:
        return []


def _walk_messages(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if "msg_name" in value or "msg_data" in value or "events" in value:
            found.append(value)
        else:
            for child in value.values():
                found.extend(_walk_messages(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_walk_messages(child))
    return found


def _matches_player(payload: dict[str, Any], player_id: int | str | None) -> bool:
    return player_id is None or str(payload.get("playerId")) == str(player_id)


def _format_event(event: dict[str, Any]) -> str:
    payload = event.get("payload") or {}
    return f"- round={event.get('round')} type={event.get('type')} action={payload.get('action')} error={payload.get('errorCode')}"
