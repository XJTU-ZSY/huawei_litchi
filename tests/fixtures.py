from __future__ import annotations

from typing import Any


def start_message_data() -> dict[str, Any]:
    return {
        "matchId": "match_test",
        "round": 1,
        "players": [
            {"playerId": 1001, "teamId": "RED"},
            {"playerId": 2002, "teamId": "BLUE"},
        ],
        "map": {
            "gameplay": {
                "roles": {
                    "startNodeId": "S01",
                    "gateNodeId": "S14",
                    "terminalNodeIds": ["S15"],
                },
                "processNodes": [
                    {"nodeId": "S02", "processType": "TRANSFER", "processRound": 4},
                    {"nodeId": "S14", "processType": "VERIFY", "processRound": 6},
                ],
            }
        },
        "nodes": [
            {"nodeId": "S01", "nodeType": "START"},
            {"nodeId": "S02", "nodeType": "POST", "processType": "TRANSFER", "processRound": 4},
            {"nodeId": "S14", "nodeType": "GATE", "processType": "VERIFY", "processRound": 6},
            {"nodeId": "S15", "nodeType": "FINISH", "terminal": True},
        ],
        "edges": [
            {"edgeId": "E01", "fromNodeId": "S01", "toNodeId": "S02", "distance": 4, "bidirectional": True},
            {"edgeId": "E02", "fromNodeId": "S02", "toNodeId": "S14", "distance": 5, "bidirectional": True},
            {"edgeId": "E03", "fromNodeId": "S14", "toNodeId": "S15", "distance": 1, "bidirectional": True},
        ],
    }


def player_state(
    *,
    node_id: str,
    state: str = "IDLE",
    next_node_id: str | None = None,
    verified: bool = False,
    delivered: bool = False,
    good_fruit: int = 100,
    freshness: float = 100.0,
    current_process: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "playerId": 1001,
        "teamId": "RED",
        "state": state,
        "currentNodeId": node_id,
        "nextNodeId": next_node_id,
        "verified": verified,
        "delivered": delivered,
        "retired": False,
        "goodFruit": good_fruit,
        "freshness": freshness,
        "currentProcess": current_process,
        "resources": {},
    }


def inquire_data(
    *,
    player: dict[str, Any],
    round_number: int = 1,
    phase: str = "NORMAL",
    events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "matchId": "match_test",
        "round": round_number,
        "phase": phase,
        "players": [player, {"playerId": 2002, "teamId": "BLUE", "state": "IDLE", "currentNodeId": "S01"}],
        "nodes": [
            {"nodeId": "S01", "processType": None, "processRound": 0, "hasObstacle": False},
            {"nodeId": "S02", "processType": "TRANSFER", "processRound": 4, "hasObstacle": False},
            {"nodeId": "S14", "processType": "VERIFY", "processRound": 6, "hasObstacle": False},
            {"nodeId": "S15", "processType": None, "processRound": 0, "hasObstacle": False, "terminal": True},
        ],
        "events": events or [],
    }
