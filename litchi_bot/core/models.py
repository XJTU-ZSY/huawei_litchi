from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


BLOCKING_STATES = {
    "PROCESSING",
    "VERIFYING",
    "FORCED_PASSING",
    "RESTING",
    "CONTESTING",
    "RETIRED",
}


@dataclass(frozen=True)
class Edge:
    edge_id: str
    from_node_id: str
    to_node_id: str
    route_type: str = ""
    distance: int = 1
    bidirectional: bool = True

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> "Edge | None":
        from_node = raw.get("fromNodeId") or raw.get("fromNode")
        to_node = raw.get("toNodeId") or raw.get("toNode")
        if not from_node or not to_node:
            return None

        return cls(
            edge_id=str(raw.get("edgeId") or f"{from_node}->{to_node}"),
            from_node_id=str(from_node),
            to_node_id=str(to_node),
            route_type=str(raw.get("routeType") or ""),
            distance=max(_as_int(raw.get("distance"), 1), 1),
            bidirectional=_as_bool(raw.get("bidirectional"), True),
        )


@dataclass(frozen=True)
class ProcessNode:
    node_id: str
    process_type: str
    process_round: int = 0

    @property
    def is_gate_verify(self) -> bool:
        return self.process_type == "VERIFY"

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> "ProcessNode | None":
        node_id = raw.get("nodeId")
        process_type = raw.get("processType")
        if not node_id or not process_type:
            return None
        return cls(
            node_id=str(node_id),
            process_type=str(process_type),
            process_round=_as_int(raw.get("processRound"), 0),
        )


@dataclass(frozen=True)
class PlayerState:
    player_id: int | str
    team_id: str | None
    state: str
    current_node_id: str | None
    next_node_id: str | None
    verified: bool
    delivered: bool
    retired: bool
    good_fruit: int
    freshness: float
    current_process: dict[str, Any] | None = None
    resources: dict[str, int] = field(default_factory=dict)

    @property
    def is_blocked(self) -> bool:
        return self.state in BLOCKING_STATES or self.current_process is not None

    @property
    def can_deliver(self) -> bool:
        return (
            not self.delivered
            and self.verified
            and self.good_fruit > 0
            and self.freshness > 0
            and not self.is_blocked
        )

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> "PlayerState | None":
        player_id = raw.get("playerId")
        if player_id is None:
            return None

        resources = raw.get("resources")
        if not isinstance(resources, dict):
            resources = {}

        return cls(
            player_id=normalize_player_id(player_id),
            team_id=str(raw["teamId"]) if raw.get("teamId") is not None else None,
            state=str(raw.get("state") or "IDLE"),
            current_node_id=str(raw["currentNodeId"]) if raw.get("currentNodeId") else None,
            next_node_id=str(raw["nextNodeId"]) if raw.get("nextNodeId") else None,
            verified=_as_bool(raw.get("verified"), False),
            delivered=_as_bool(raw.get("delivered"), False),
            retired=_as_bool(raw.get("retired"), False),
            good_fruit=_as_int(raw.get("goodFruit"), 0),
            freshness=_as_float(raw.get("freshness"), 0.0),
            current_process=raw.get("currentProcess") if isinstance(raw.get("currentProcess"), dict) else None,
            resources={str(key): _as_int(value, 0) for key, value in resources.items()},
        )


@dataclass(frozen=True)
class NodeState:
    node_id: str
    process_type: str | None = None
    process_round: int = 0
    has_obstacle: bool = False
    resource_stock: dict[str, int] = field(default_factory=dict)

    @property
    def requires_process(self) -> bool:
        return bool(self.process_type and self.process_type != "VERIFY" and self.process_round >= 0)

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> "NodeState | None":
        node_id = raw.get("nodeId")
        if not node_id:
            return None

        resource_stock = raw.get("resourceStock")
        if not isinstance(resource_stock, dict):
            resource_stock = {}

        process_type = raw.get("processType")
        return cls(
            node_id=str(node_id),
            process_type=str(process_type) if process_type else None,
            process_round=_as_int(raw.get("processRound"), 0),
            has_obstacle=_as_bool(raw.get("hasObstacle"), False),
            resource_stock={str(key): _as_int(value, 0) for key, value in resource_stock.items()},
        )


def normalize_player_id(value: Any) -> int | str:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return str(value)


def _as_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes"}
    return bool(value)


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
