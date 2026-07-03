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
    action_counts: dict[str, Counter[str]] = {}
    routes: dict[str, list[dict[str, Any]]] = {}
    task_completions: dict[str, list[dict[str, Any]]] = {}
    resource_events: dict[str, list[dict[str, Any]]] = {}
    window_cards: Counter[str] = Counter()
    window_reveals: list[dict[str, Any]] = []
    scores: dict[str, Any] = {}
    deliveries: dict[str, Any] = {}
    final_players: dict[str, Any] = {}
    final_player_rounds: dict[str, Any] = {}
    latest_players: dict[str, Any] = {}
    latest_player_rounds: dict[str, Any] = {}

    for message in messages:
        name = message.get("msg_name")
        data = message.get("msg_data") or message
        if name == "over":
            for player in data.get("players") or []:
                player_key = str(player.get("playerId"))
                scores[player_key] = player.get("totalScore")
                final_players[player_key] = player
                final_player_rounds[player_key] = data.get("round")
        for player in data.get("players") or []:
            if player.get("playerId") is not None:
                player_key = str(player.get("playerId"))
                latest_players[player_key] = player
                latest_player_rounds[player_key] = data.get("round")
        for result in data.get("actionResults") or []:
            result_player_key = _player_key(result)
            action_name = result.get("action")
            if result_player_key and action_name:
                action_counts.setdefault(result_player_key, Counter())[str(action_name)] += 1
        for event in data.get("events") or []:
            event_type = str(event.get("type"))
            payload = event.get("payload") or {}
            event_counts[event_type] += 1
            payload_player_key = _player_key(payload)
            if payload_player_key and event_type == "NODE_ENTER":
                routes.setdefault(payload_player_key, []).append(
                    {
                        "round": event.get("round"),
                        "fromNodeId": payload.get("fromNodeId"),
                        "nodeId": payload.get("nodeId"),
                        "routeEdgeId": payload.get("routeEdgeId"),
                    }
                )
            elif payload_player_key and event_type == "TASK_COMPLETE":
                task_completions.setdefault(payload_player_key, []).append(
                    {
                        "round": event.get("round"),
                        "taskId": payload.get("taskId"),
                        "taskTemplateId": payload.get("taskTemplateId"),
                        "nodeId": payload.get("nodeId"),
                        "score": payload.get("score"),
                    }
                )
            elif payload_player_key and event_type in {"RESOURCE_CLAIM", "RESOURCE_USE"}:
                resource_events.setdefault(payload_player_key, []).append(
                    {
                        "round": event.get("round"),
                        "event": event_type,
                        "nodeId": payload.get("nodeId") or payload.get("targetNodeId"),
                        "resourceType": payload.get("resourceType"),
                    }
                )
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
                window_reveals.append(
                    {
                        "round": event.get("round"),
                        "contestId": payload.get("contestId"),
                        "roundIndex": payload.get("roundIndex"),
                        "redCard": payload.get("redCard"),
                        "blueCard": payload.get("blueCard"),
                        "redPoint": payload.get("redPoint"),
                        "bluePoint": payload.get("bluePoint"),
                    }
                )

    _infer_deliveries_from_players(deliveries, final_players, final_player_rounds, player_id, "finalPlayer")
    _infer_deliveries_from_players(deliveries, latest_players, latest_player_rounds, player_id, "latestPlayer")

    return {
        "messageCount": len(messages),
        "eventCounts": dict(event_counts),
        "rejectedCount": len(rejected),
        "invalidCount": len(invalid),
        "rejected": rejected[:20],
        "invalid": invalid[:20],
        "actionCounts": {player_key: dict(counts) for player_key, counts in action_counts.items()},
        "routes": routes,
        "taskCompletions": task_completions,
        "resourceEvents": resource_events,
        "windowCards": dict(window_cards),
        "windowReveals": window_reveals,
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
        f"action counts: {summary.get('actionCounts', {})}",
        f"routes: {_format_routes(summary.get('routes') or {})}",
        f"task completions: {_format_task_completions(summary.get('taskCompletions') or {})}",
        f"resource events: {_format_resource_events(summary.get('resourceEvents') or {})}",
        f"window cards: {summary['windowCards']}",
        f"window reveals: {_format_window_reveals(summary.get('windowReveals') or [])}",
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


def _player_key(value: dict[str, Any]) -> str | None:
    player_id = value.get("playerId")
    if player_id is None:
        return None
    return str(player_id)


def _infer_deliveries_from_players(
    deliveries: dict[str, Any],
    players: dict[str, dict[str, Any]],
    player_rounds: dict[str, Any],
    player_id: int | str | None,
    source: str,
) -> None:
    for player_key, player in players.items():
        if player_key in deliveries:
            continue
        if not _matches_player(player, player_id):
            continue
        if player.get("delivered") is not True:
            continue
        deliveries[player_key] = {
            "round": _delivery_round(player, player_rounds.get(player_key)),
            "goodFruit": player.get("goodFruit"),
            "freshness": player.get("freshness"),
            "source": source,
            "inferred": True,
        }


def _delivery_round(player: dict[str, Any], fallback_round: Any = None) -> Any:
    for key in ("deliveryRound", "deliveredRound", "deliverRound", "round"):
        if player.get(key) is not None:
            return player.get(key)
    return fallback_round


def _format_event(event: dict[str, Any]) -> str:
    payload = event.get("payload") or {}
    return f"- round={event.get('round')} type={event.get('type')} action={payload.get('action')} error={payload.get('errorCode')}"


def _format_routes(routes: dict[str, list[dict[str, Any]]]) -> dict[str, list[str]]:
    return {
        player_key: _limit_items(
            [
                _join_nonempty(
                    [
                        f"{item.get('fromNodeId')}->{item.get('nodeId')}"
                        if item.get("fromNodeId")
                        else str(item.get("nodeId")),
                        f"@{item.get('round')}",
                    ]
                )
                for item in items
            ]
        )
        for player_key, items in routes.items()
    }


def _format_task_completions(task_completions: dict[str, list[dict[str, Any]]]) -> dict[str, list[str]]:
    return {
        player_key: _limit_items(
            [
                _join_nonempty(
                    [
                        str(item.get("taskId") or item.get("taskTemplateId") or "task"),
                        str(item.get("nodeId") or ""),
                        f"score={item.get('score')}" if item.get("score") is not None else "",
                        f"@{item.get('round')}",
                    ],
                    separator=":",
                )
                for item in items
            ]
        )
        for player_key, items in task_completions.items()
    }


def _format_resource_events(resource_events: dict[str, list[dict[str, Any]]]) -> dict[str, list[str]]:
    return {
        player_key: _limit_items(
            [
                _join_nonempty(
                    [
                        str(item.get("event") or "RESOURCE"),
                        str(item.get("resourceType") or ""),
                        str(item.get("nodeId") or ""),
                        f"@{item.get('round')}",
                    ],
                    separator=":",
                )
                for item in items
            ]
        )
        for player_key, items in resource_events.items()
    }


def _format_window_reveals(window_reveals: list[dict[str, Any]]) -> list[str]:
    return _limit_items(
        [
            _join_nonempty(
                [
                    str(item.get("contestId") or "contest"),
                    f"roundIndex={item.get('roundIndex')}",
                    f"red={item.get('redCard')}",
                    f"blue={item.get('blueCard')}",
                    f"points={item.get('redPoint')}-{item.get('bluePoint')}",
                    f"@{item.get('round')}",
                ],
                separator=" ",
            )
            for item in window_reveals
        ]
    )


def _join_nonempty(items: list[str], separator: str = "") -> str:
    return separator.join(item for item in items if item)


def _limit_items(items: list[str], limit: int = 20) -> list[str]:
    if len(items) <= limit:
        return items
    remaining = len(items) - limit
    return [*items[:limit], f"...(+{remaining} more)"]
