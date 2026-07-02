from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .graph import MapGraph
from .models import NodeState, PlayerState, ProcessNode, normalize_player_id


@dataclass(frozen=True)
class StaticGame:
    player_id: int | str
    team_id: str | None
    opponent_team_id: str | None
    start_node_id: str
    gate_node_id: str
    terminal_node_ids: tuple[str, ...]
    graph: MapGraph
    process_nodes: dict[str, ProcessNode]

    @classmethod
    def from_start(cls, start_data: dict[str, Any], player_id: int | str) -> "StaticGame":
        normalized_player_id = normalize_player_id(player_id)
        players = start_data.get("players")
        if not isinstance(players, list):
            players = []

        team_id = None
        opponent_team_id = None
        for raw_player in players:
            if not isinstance(raw_player, dict):
                continue
            raw_player_id = normalize_player_id(raw_player.get("playerId"))
            raw_team_id = str(raw_player["teamId"]) if raw_player.get("teamId") is not None else None
            if raw_player_id == normalized_player_id:
                team_id = raw_team_id
            elif opponent_team_id is None:
                opponent_team_id = raw_team_id

        gameplay = _gameplay(start_data)
        roles = gameplay.get("roles") if isinstance(gameplay.get("roles"), dict) else {}
        terminal_node_ids = roles.get("terminalNodeIds") or ["S15"]
        if not isinstance(terminal_node_ids, list):
            terminal_node_ids = [str(terminal_node_ids)]

        process_nodes: dict[str, ProcessNode] = {}
        for source in (gameplay.get("processNodes"), start_data.get("nodes")):
            if not isinstance(source, list):
                continue
            for raw_node in source:
                if not isinstance(raw_node, dict):
                    continue
                process_node = ProcessNode.from_raw(raw_node)
                if process_node is not None:
                    process_nodes[process_node.node_id] = process_node

        return cls(
            player_id=normalized_player_id,
            team_id=team_id,
            opponent_team_id=opponent_team_id,
            start_node_id=str(roles.get("startNodeId") or "S01"),
            gate_node_id=str(roles.get("gateNodeId") or "S14"),
            terminal_node_ids=tuple(str(node_id) for node_id in terminal_node_ids),
            graph=MapGraph.from_raw_edges(_edges(start_data)),
            process_nodes=process_nodes,
        )


@dataclass(frozen=True)
class TurnState:
    round_number: int
    phase: str
    me: PlayerState | None
    nodes: dict[str, NodeState]
    raw_events: list[dict[str, Any]]

    @classmethod
    def from_inquire(cls, inquire_data: dict[str, Any], static_game: StaticGame) -> "TurnState":
        players = inquire_data.get("players")
        if not isinstance(players, list):
            players = []

        me = None
        for raw_player in players:
            if not isinstance(raw_player, dict):
                continue
            player = PlayerState.from_raw(raw_player)
            if player is not None and player.player_id == static_game.player_id:
                me = player
                break

        nodes: dict[str, NodeState] = {}
        raw_nodes = inquire_data.get("nodes")
        if isinstance(raw_nodes, list):
            for raw_node in raw_nodes:
                if isinstance(raw_node, dict):
                    node = NodeState.from_raw(raw_node)
                    if node is not None:
                        nodes[node.node_id] = node

        events = inquire_data.get("events")
        if not isinstance(events, list):
            events = []

        return cls(
            round_number=_as_int(inquire_data.get("round"), 0),
            phase=str(inquire_data.get("phase") or "NORMAL"),
            me=me,
            nodes=nodes,
            raw_events=[event for event in events if isinstance(event, dict)],
        )

    def node_state(self, node_id: str | None) -> NodeState | None:
        if node_id is None:
            return None
        return self.nodes.get(node_id)


def _gameplay(start_data: dict[str, Any]) -> dict[str, Any]:
    map_data = start_data.get("map")
    if isinstance(map_data, dict):
        gameplay = map_data.get("gameplay")
        if isinstance(gameplay, dict):
            return gameplay
    return {}


def _edges(start_data: dict[str, Any]) -> list[dict[str, Any]]:
    edges = start_data.get("edges")
    if isinstance(edges, list):
        return [edge for edge in edges if isinstance(edge, dict)]

    map_data = start_data.get("map")
    if isinstance(map_data, dict) and isinstance(map_data.get("edges"), list):
        return [edge for edge in map_data["edges"] if isinstance(edge, dict)]

    return []


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
