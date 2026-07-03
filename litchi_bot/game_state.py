from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .graph import RouteGraph


def same_player_id(left: Any, right: Any) -> bool:
    return str(left) == str(right)


@dataclass
class GameContext:
    match_id: str
    player_id: int | str
    team_id: str
    opponent_player_id: int | str | None
    opponent_team_id: str | None
    start_round: int
    duration_round: int
    start_node_id: str
    gate_node_id: str
    terminal_node_id: str
    graph: RouteGraph
    raw_start: dict[str, Any]


@dataclass
class GameSnapshot:
    round_no: int
    phase: str
    self_player: dict[str, Any]
    opponent_player: dict[str, Any] | None
    nodes_by_id: dict[str, dict[str, Any]]
    tasks: list[dict[str, Any]]
    contests: list[dict[str, Any]]
    events: list[dict[str, Any]]
    action_results: list[dict[str, Any]]
    weather: dict[str, Any]
    raw: dict[str, Any]


@dataclass
class GameMemory:
    player_id: int | str
    context: GameContext | None = None
    completed_process_nodes: set[str] = field(default_factory=set)
    process_idle_yield_counts: dict[str, int] = field(default_factory=dict)
    process_contest_counts: dict[str, int] = field(default_factory=dict)
    contested_resource_nodes: set[str] = field(default_factory=set)
    contested_resources: set[tuple[str, str]] = field(default_factory=set)
    completed_tasks: set[str] = field(default_factory=set)
    process_required_task_ids: set[str] = field(default_factory=set)
    process_required_task_nodes: set[str] = field(default_factory=set)
    rejected_actions: list[dict[str, Any]] = field(default_factory=list)

    def apply_start(self, data: dict[str, Any]) -> GameContext:
        players = data.get("players", [])
        self_player = next((p for p in players if same_player_id(p.get("playerId"), self.player_id)), None)
        if self_player is None:
            raise ValueError(f"playerId {self.player_id!r} not present in start.players")
        opponent = next((p for p in players if not same_player_id(p.get("playerId"), self.player_id)), None)
        gameplay = (data.get("map") or {}).get("gameplay") or {}
        roles = gameplay.get("roles") or {}
        nodes = data.get("nodes") or (data.get("map") or {}).get("nodes") or []
        terminal = self._find_terminal_node(nodes)
        context = GameContext(
            match_id=str(data["matchId"]),
            player_id=self.player_id,
            team_id=str(self_player.get("teamId")),
            opponent_player_id=None if opponent is None else opponent.get("playerId"),
            opponent_team_id=None if opponent is None else opponent.get("teamId"),
            start_round=int(data.get("round") or 1),
            duration_round=int(data.get("durationRound") or 600),
            start_node_id=str(roles.get("startNodeId") or self._find_start_node(nodes) or "S01"),
            gate_node_id=str(roles.get("gateNodeId") or "S14"),
            terminal_node_id=str((roles.get("terminalNodeIds") or [terminal or "S15"])[0]),
            graph=RouteGraph.from_raw_edges(data.get("edges") or (data.get("map") or {}).get("edges") or []),
            raw_start=data,
        )
        self.context = context
        return context

    def apply_inquire(self, data: dict[str, Any]) -> GameSnapshot:
        if self.context is None:
            raise ValueError("cannot apply inquire before start")
        players = data.get("players") or []
        self_player = next((p for p in players if same_player_id(p.get("playerId"), self.player_id)), {})
        self._record_events(data.get("events") or [], current_node_id=self_player.get("currentNodeId"))
        self._record_action_results(data.get("actionResults") or [], current_node_id=self_player.get("currentNodeId"))
        opponent = next((p for p in players if not same_player_id(p.get("playerId"), self.player_id)), None)
        nodes = data.get("nodes") or []
        edges = data.get("edges")
        if edges:
            self.context.graph = RouteGraph.from_raw_edges(edges)
        return GameSnapshot(
            round_no=int(data.get("round") or 0),
            phase=str(data.get("phase") or "NORMAL"),
            self_player=self_player,
            opponent_player=opponent,
            nodes_by_id={str(n.get("nodeId")): n for n in nodes if n.get("nodeId")},
            tasks=list(data.get("tasks") or []),
            contests=list(data.get("contests") or []),
            events=list(data.get("events") or []),
            action_results=list(data.get("actionResults") or []),
            weather=dict(data.get("weather") or {}),
            raw=data,
        )

    def _record_events(self, events: list[dict[str, Any]], current_node_id: Any = None) -> None:
        last_resource_claim_complete: dict[str, Any] | None = None
        for event in events:
            payload = event.get("payload") or {}
            if payload.get("playerId") is not None and not same_player_id(payload.get("playerId"), self.player_id):
                continue
            event_type = event.get("type")
            if event_type == "PROCESS_COMPLETE":
                if self._is_resource_claim_process_complete(payload):
                    last_resource_claim_complete = payload
                node_id = payload.get("targetNodeId") or payload.get("nodeId")
                if node_id and self._is_fixed_node_process_complete(payload):
                    self.completed_process_nodes.add(str(node_id))
                    self.process_contest_counts.pop(str(node_id), None)
                    self.process_idle_yield_counts.pop(str(node_id), None)
                    self.process_required_task_nodes.discard(str(node_id))
            elif event_type == "TASK_COMPLETE":
                task_id = payload.get("taskId")
                if task_id:
                    self.completed_tasks.add(str(task_id))
            elif event_type == "WINDOW_CONTEST_START":
                self._record_resource_contest(payload, current_node_id)
            elif event_type in {"ACTION_REJECTED", "INVALID_ACTION"}:
                self.rejected_actions.append(event)
                self._recover_from_rejection(payload, current_node_id, fallback_payload=last_resource_claim_complete)

    def _record_action_results(self, action_results: list[dict[str, Any]], current_node_id: Any = None) -> None:
        for result in action_results:
            payload = result.get("payload") or result
            if payload.get("playerId") is not None and not same_player_id(payload.get("playerId"), self.player_id):
                continue
            self._record_resource_contest(payload, current_node_id)
            self._record_process_contest(payload, current_node_id)
            self._recover_from_rejection(payload, current_node_id)

    def _record_resource_contest(self, payload: dict[str, Any], current_node_id: Any = None) -> None:
        action = str(payload.get("action") or "").upper()
        contest_type = str(payload.get("contestType") or "").upper()
        result_text = f"{payload.get('result') or ''} {payload.get('message') or ''}".upper()
        is_resource_contest = contest_type == "RESOURCE" or (
            action == "CLAIM_RESOURCE" and "CONTEST_CREATED" in result_text
        )
        if not is_resource_contest:
            return

        node_id = payload.get("targetNodeId") or payload.get("nodeId") or current_node_id
        if not node_id:
            return
        node_key = str(node_id)
        if current_node_id is not None and node_key != str(current_node_id):
            return
        self.contested_resource_nodes.add(node_key)

        resource_type = payload.get("resourceType")
        if resource_type:
            self.contested_resources.add((node_key, str(resource_type)))

    @staticmethod
    def _is_fixed_node_process_complete(payload: dict[str, Any]) -> bool:
        action = str(payload.get("action") or "").upper()
        object_key = str(payload.get("objectKey") or "")
        return action == "PROCESS" or object_key.startswith("PROCESS:")

    @staticmethod
    def _is_resource_claim_process_complete(payload: dict[str, Any]) -> bool:
        action = str(payload.get("action") or "").upper()
        object_key = str(payload.get("objectKey") or "")
        return action == "CLAIM_RESOURCE" or object_key.startswith("RESOURCE:")

    def _record_process_contest(self, payload: dict[str, Any], current_node_id: Any = None) -> None:
        if str(payload.get("action") or "").upper() != "PROCESS":
            return
        if payload.get("accepted") is not True:
            return
        result_text = f"{payload.get('result') or ''} {payload.get('message') or ''}".upper()
        if "CONTEST_CREATED" not in result_text:
            return
        node_id = payload.get("targetNodeId") or payload.get("currentNodeId") or payload.get("nodeId") or current_node_id
        if node_id:
            node_key = str(node_id)
            self.process_contest_counts[node_key] = self.process_contest_counts.get(node_key, 0) + 1

    def _recover_from_rejection(
        self,
        payload: dict[str, Any],
        current_node_id: Any = None,
        *,
        fallback_payload: dict[str, Any] | None = None,
    ) -> None:
        error_code = str(payload.get("errorCode") or "").upper()
        action = str(payload.get("action") or "").upper()
        if error_code == "RESOURCE_NOT_ENOUGH" and action == "CLAIM_RESOURCE":
            self._record_depleted_resource(payload, current_node_id, fallback_payload=fallback_payload)
            return
        if error_code != "PROCESS_REQUIRED":
            return
        node_id = payload.get("targetNodeId") or payload.get("currentNodeId") or payload.get("nodeId") or current_node_id
        if node_id:
            self.completed_process_nodes.discard(str(node_id))
        if action == "CLAIM_TASK":
            task_id = payload.get("taskId")
            if task_id:
                self.process_required_task_ids.add(str(task_id))
            if node_id:
                self.process_required_task_nodes.add(str(node_id))

    def _record_depleted_resource(
        self,
        payload: dict[str, Any],
        current_node_id: Any = None,
        *,
        fallback_payload: dict[str, Any] | None = None,
    ) -> None:
        node_id = (
            payload.get("targetNodeId")
            or payload.get("currentNodeId")
            or payload.get("nodeId")
            or self._resource_node_from_payload(fallback_payload)
            or current_node_id
        )
        if not node_id:
            return
        node_key = str(node_id)
        resource_type = payload.get("resourceType") or self._resource_type_from_payload(fallback_payload)
        if resource_type:
            self.contested_resources.add((node_key, str(resource_type)))
        else:
            self.contested_resource_nodes.add(node_key)

    @staticmethod
    def _resource_node_from_payload(payload: dict[str, Any] | None) -> str | None:
        if not payload:
            return None
        node_id = payload.get("targetNodeId") or payload.get("currentNodeId") or payload.get("nodeId")
        if node_id:
            return str(node_id)
        parts = str(payload.get("objectKey") or "").split(":")
        if len(parts) >= 3 and parts[0] == "RESOURCE":
            return parts[1]
        return None

    @staticmethod
    def _resource_type_from_payload(payload: dict[str, Any] | None) -> str | None:
        if not payload:
            return None
        resource_type = payload.get("resourceType")
        if resource_type:
            return str(resource_type)
        parts = str(payload.get("objectKey") or "").split(":")
        if len(parts) >= 3 and parts[0] == "RESOURCE":
            return parts[2]
        return None

    @staticmethod
    def _find_start_node(nodes: list[dict[str, Any]]) -> str | None:
        for node in nodes:
            if node.get("start") is True:
                return str(node.get("nodeId"))
        return None

    @staticmethod
    def _find_terminal_node(nodes: list[dict[str, Any]]) -> str | None:
        for node in nodes:
            if node.get("terminal") is True:
                return str(node.get("nodeId"))
        return None
