from __future__ import annotations

from typing import Any, Iterable


def registration(player_id: int | str, player_name: str, version: str) -> dict[str, Any]:
    return {
        "msg_name": "registration",
        "msg_data": {
            "playerId": _player_id(player_id),
            "playerName": player_name,
            "version": version,
        },
    }


def ready(match_id: str, round_number: int, player_id: int | str) -> dict[str, Any]:
    return {
        "msg_name": "ready",
        "msg_data": {
            "matchId": match_id,
            "round": round_number,
            "playerId": _player_id(player_id),
        },
    }


def action(
    match_id: str,
    round_number: int,
    player_id: int | str,
    actions: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "msg_name": "action",
        "msg_data": {
            "matchId": match_id,
            "round": round_number,
            "playerId": _player_id(player_id),
            "actions": list(actions) if actions is not None else [],
        },
    }


def _player_id(value: int | str) -> int | str:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return value
