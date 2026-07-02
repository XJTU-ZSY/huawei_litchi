from __future__ import annotations

from typing import Any


def parse_player_id(value: str) -> int | str:
    text = str(value).strip()
    if text.isdigit():
        return int(text)
    return text


def registration(player_id: int | str, player_name: str = "litchi-python", version: str = "0.1.0") -> dict[str, Any]:
    return {
        "msg_name": "registration",
        "msg_data": {
            "playerId": player_id,
            "playerName": player_name,
            "version": version,
        },
    }


def ready(match_id: str, round_no: int, player_id: int | str) -> dict[str, Any]:
    return {
        "msg_name": "ready",
        "msg_data": {
            "matchId": match_id,
            "round": round_no,
            "playerId": player_id,
        },
    }


def action(match_id: str, round_no: int, player_id: int | str, actions: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "msg_name": "action",
        "msg_data": {
            "matchId": match_id,
            "round": round_no,
            "playerId": player_id,
            "actions": actions,
        },
    }
