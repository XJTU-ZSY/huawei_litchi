from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .graph import RouteGraph
from .protocol import error_recovery_policy, normalize_error_code


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
    skipped_process_nodes: set[str] = field(default_factory=set)
    active_process_contests: dict[str, str] = field(default_factory=dict)
    active_resource_contests: dict[str, str] = field(default_factory=dict)
    active_task_contests: dict[str, str] = field(default_factory=dict)
    skipped_resource_claims: set[str] = field(default_factory=set)
    skipped_task_claims: set[str] = field(default_factory=set)
    drawn_task_retry_counts: dict[str, int] = field(default_factory=dict)
    drawn_process_yield_counts: dict[str, int] = field(default_factory=dict)
    drawn_process_retry_counts: dict[str, int] = field(default_factory=dict)
    process_idle_yield_counts: dict[str, int] = field(default_factory=dict)
    completed_tasks: set[str] = field(default_factory=set)
    rejected_actions: list[dict[str, Any]] = field(default_factory=list)
    error_counts: dict[str, int] = field(default_factory=dict)
    last_error_code: str | None = None
    last_error_policy: str | None = None
    blocked_move_targets: set[str] = field(default_factory=set)
    forced_pass_blocked_nodes: set[str] = field(default_factory=set)
    delivery_requires_verification: bool = False

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
        for event in events:
            payload = event.get("payload") or {}
            if payload.get("playerId") is not None and not same_player_id(payload.get("playerId"), self.player_id):
                continue
            event_type = event.get("type")
            if event_type == "WINDOW_CONTEST_START":
                self._record_window_contest_start(payload)
            elif event_type in {"WINDOW_CONTEST_END", "WINDOW_CONTEST_DRAW"}:
                self._record_window_contest_result(event_type, payload)
            elif event_type == "NODE_ENTER":
                self._record_node_enter(payload)
            elif event_type in {"GUARD_BREAK", "OBSTACLE_CLEAR", "FORCED_PASS_END"}:
                node_id = payload.get("targetNodeId") or payload.get("nodeId")
                if node_id:
                    self.blocked_move_targets.discard(str(node_id))
            elif event_type == "PROCESS_COMPLETE":
                node_id = payload.get("targetNodeId") or payload.get("nodeId")
                if node_id and self._is_fixed_node_process_complete(payload):
                    self.completed_process_nodes.add(str(node_id))
                    self.skipped_process_nodes.discard(str(node_id))
                    self.drawn_process_yield_counts.pop(str(node_id), None)
                    self.drawn_process_retry_counts.pop(str(node_id), None)
            elif event_type == "TASK_COMPLETE":
                task_id = payload.get("taskId")
                if task_id:
                    self.completed_tasks.add(str(task_id))
                    self.skipped_task_claims.discard(str(task_id))
                    self.drawn_task_retry_counts.pop(str(task_id), None)
            elif event_type in {"ACTION_REJECTED", "INVALID_ACTION"}:
                self.rejected_actions.append(event)
                self._recover_from_rejection(payload, current_node_id)

    def _record_action_results(self, action_results: list[dict[str, Any]], current_node_id: Any = None) -> None:
        for result in action_results:
            payload = result.get("payload") or result
            if payload.get("playerId") is not None and not same_player_id(payload.get("playerId"), self.player_id):
                continue
            if payload.get("accepted") is False or payload.get("errorCode"):
                self._recover_from_rejection(payload, current_node_id)

    def _record_node_enter(self, payload: dict[str, Any]) -> None:
        node_id = payload.get("nodeId") or payload.get("targetNodeId")
        if not node_id:
            return
        node_key = str(node_id)
        self.completed_process_nodes.discard(node_key)
        self.skipped_process_nodes.discard(node_key)
        self.drawn_process_yield_counts.pop(node_key, None)
        self.drawn_process_retry_counts.pop(node_key, None)
        self.process_idle_yield_counts.pop(node_key, None)
        self.blocked_move_targets.discard(node_key)

    @staticmethod
    def _is_fixed_node_process_complete(payload: dict[str, Any]) -> bool:
        action = str(payload.get("action") or "").upper()
        object_key = str(payload.get("objectKey") or "")
        return action == "PROCESS" or object_key.startswith("PROCESS:")

    def _record_window_contest_start(self, payload: dict[str, Any]) -> None:
        contest_id = payload.get("contestId")
        if not contest_id:
            return
        object_key = str(payload.get("objectKey") or "")
        contest_type = str(payload.get("contestType") or "").upper()
        task_id = self.task_id_from_object(object_key, payload.get("taskId"))
        if task_id and (object_key.startswith("TASK:") or contest_type == "TASK"):
            self.active_task_contests[str(contest_id)] = task_id
            return
        resource_key = self.resource_claim_key_from_object(object_key, payload.get("targetNodeId"), payload.get("resourceType"))
        if resource_key and (object_key.startswith("RESOURCE:") or contest_type == "RESOURCE"):
            self.active_resource_contests[str(contest_id)] = resource_key
            return
        node_id = self._process_node_from_object_key(object_key, payload.get("targetNodeId"))
        if node_id:
            self.active_process_contests[str(contest_id)] = node_id

    def _record_window_contest_result(self, event_type: Any, payload: dict[str, Any]) -> None:
        contest_id = payload.get("contestId")
        if not contest_id:
            return
        is_draw = event_type == "WINDOW_CONTEST_DRAW" or str(payload.get("winnerTeamId") or "").upper() == "DRAW"
        task_id = self.active_task_contests.pop(str(contest_id), None)
        if is_draw and task_id:
            self.skipped_task_claims.add(task_id)
        node_id = self.active_process_contests.pop(str(contest_id), None)
        if is_draw and node_id:
            self.skipped_process_nodes.add(node_id)
            self.drawn_process_yield_counts.pop(node_id, None)
        resource_key = self.active_resource_contests.pop(str(contest_id), None)
        if is_draw and resource_key:
            self.skipped_resource_claims.add(resource_key)

    @staticmethod
    def _process_node_from_object_key(object_key: Any, fallback_node_id: Any = None) -> str | None:
        text = str(object_key or "")
        if text.startswith("PROCESS:"):
            parts = text.split(":")
            if len(parts) >= 2 and parts[1]:
                return parts[1]
        if fallback_node_id:
            return str(fallback_node_id)
        return None

    def _recover_from_rejection(self, payload: dict[str, Any], current_node_id: Any = None) -> None:
        error_code = normalize_error_code(payload.get("errorCode"))
        if not error_code:
            return
        self.last_error_code = error_code
        self.last_error_policy = error_recovery_policy(error_code)
        self.error_counts[error_code] = self.error_counts.get(error_code, 0) + 1
        node_id = payload.get("targetNodeId") or payload.get("currentNodeId") or payload.get("nodeId") or current_node_id
        node_key = str(node_id) if node_id else ""
        action_name = str(payload.get("action") or "").upper()
        object_key = str(payload.get("objectKey") or "")

        if error_code == "PROCESS_REQUIRED":
            if node_key:
                self.completed_process_nodes.discard(node_key)
                self.skipped_process_nodes.discard(node_key)
                self.drawn_process_yield_counts.pop(node_key, None)
                self.drawn_process_retry_counts.pop(node_key, None)
            return

        if error_code in {"PROCESS_NOT_AVAILABLE", "NOT_AT_TARGET_NODE"} and node_key:
            self.completed_process_nodes.discard(node_key)
            self.skipped_process_nodes.add(node_key)

        if error_code in {"MOVE_BLOCKED_BY_GUARD", "MOVE_EDGE_NOT_FOUND", "TARGET_NOT_REACHABLE"} and node_key:
            self.blocked_move_targets.add(node_key)

        if error_code == "FORCED_PASS_REPEAT" and node_key:
            self.forced_pass_blocked_nodes.add(node_key)

        if error_code in {"VERIFY_REQUIRED", "DELIVER_NOT_VERIFIED"}:
            self.delivery_requires_verification = True
        elif error_code == "ALREADY_VERIFIED":
            self.delivery_requires_verification = False

        if error_code in {"TASK_NOT_FOUND", "TASK_PROTECTED", "TASK_REQUIREMENT_NOT_MET", "TASK_EXPIRED"}:
            task_id = self.task_id_from_object(object_key, payload.get("taskId"))
            if task_id:
                self.skipped_task_claims.add(task_id)

        if error_code in {"OBJECT_BUSY", "WINDOW_DRAW_RETRY_LIMIT"}:
            self._skip_object_from_rejection(payload)

        if error_code in {"RESOURCE_NOT_ENOUGH", "RESOURCE_NOT_USABLE"}:
            resource_key = self.resource_claim_key_from_object(
                object_key,
                node_key,
                payload.get("resourceType"),
            )
            if action_name == "CLAIM_RESOURCE" and resource_key:
                self.skipped_resource_claims.add(resource_key)
            if action_name == "USE_RESOURCE" and payload.get("resourceType"):
                self.skipped_resource_claims.add(f"USE_RESOURCE:{payload.get('resourceType')}")

        if error_code == "OBSTACLE_NOT_FOUND" and node_key:
            self.blocked_move_targets.discard(node_key)

    def _skip_object_from_rejection(self, payload: dict[str, Any]) -> None:
        object_key = str(payload.get("objectKey") or "")
        node_id = payload.get("targetNodeId") or payload.get("nodeId")
        task_id = self.task_id_from_object(object_key, payload.get("taskId"))
        if task_id:
            self.skipped_task_claims.add(task_id)
            return
        resource_key = self.resource_claim_key_from_object(object_key, node_id, payload.get("resourceType"))
        if resource_key:
            self.skipped_resource_claims.add(resource_key)
            return
        node_key = self._process_node_from_object_key(object_key, node_id)
        if node_key:
            self.skipped_process_nodes.add(node_key)

    @classmethod
    def resource_claim_key_from_object(
        cls,
        object_key: Any,
        fallback_node_id: Any = None,
        fallback_resource_type: Any = None,
    ) -> str | None:
        text = str(object_key or "")
        if text.startswith("RESOURCE:"):
            parts = text.split(":")
            if len(parts) >= 3 and parts[1] and parts[2]:
                return cls.resource_claim_key(parts[1], parts[2])
        if fallback_node_id and fallback_resource_type:
            return cls.resource_claim_key(fallback_node_id, fallback_resource_type)
        return None

    @staticmethod
    def task_id_from_object(object_key: Any, fallback_task_id: Any = None) -> str | None:
        if fallback_task_id:
            return str(fallback_task_id)
        text = str(object_key or "")
        if text.startswith("TASK:"):
            parts = text.split(":")
            if len(parts) >= 2 and parts[1]:
                return parts[1]
        return None

    @staticmethod
    def resource_claim_key(node_id: Any, resource_type: Any) -> str:
        return f"RESOURCE:{node_id}:{resource_type}"

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
