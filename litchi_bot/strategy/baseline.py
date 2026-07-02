from __future__ import annotations

from math import ceil
from typing import Any

from ..game_state import GameContext, GameMemory, GameSnapshot
from .contest import WindowCardSelector


RESOURCE_PRIORITY = [
    "FAST_HORSE",
    "SHORT_HORSE",
    "ICE_BOX",
    "INTEL",
    "PASS_TOKEN",
    "OFFICIAL_PERMIT",
    "BOAT_RIGHT",
]

HORSE_RESOURCES = ("FAST_HORSE", "SHORT_HORSE")
ALWAYS_CLAIM_RESOURCE_TYPES = set(HORSE_RESOURCES) | {"ICE_BOX"}
SPEED_BUFF_TYPES = {"FAST_HORSE", "SHORT_HORSE", "RUSH_SPEED"}
FIXED_PROCESS_BUSY_STATES = {"PROCESSING", "VERIFYING", "RESTING", "CONTESTING"}
IDLE_PROCESS_YIELD_LIMIT = 1
ICE_BOX_USE_FRESHNESS_LIMIT = 90.0
MIN_HORSE_TRAVEL_ROUNDS = 8
ROUND_MS = 1000
DEFAULT_GATE_VERIFY_ROUNDS = 6
BREAK_ORDER_BAD_FRUIT_COST = 2
ENDGAME_TASK_SAFETY_MARGIN_ROUNDS = 10
DELIVERY_CLOSURE_SAFETY_MARGIN_ROUNDS = 20
TASK_SCORE_TARGET = 90
TASK_CLUSTER_LOOKAHEAD_ROUNDS = 90
BONUS_TASK_MIN_SCORE = 30
BONUS_TASK_MAX_DETOUR_ROUNDS = 60


class BaselineStrategy:
    def __init__(self, memory: GameMemory) -> None:
        self.memory = memory
        self.window_selector = WindowCardSelector()
        self.last_reason = "init"

    def decide(self, context: GameContext, snapshot: GameSnapshot) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = []
        main_action = self._main_action(context, snapshot)
        if main_action is not None:
            actions.append(main_action)
        window_action = self.window_selector.choose(context, snapshot)
        if window_action is not None:
            actions.append(window_action)
        return actions

    def _main_action(self, context: GameContext, snapshot: GameSnapshot) -> dict[str, Any] | None:
        player = snapshot.self_player
        state = str(player.get("state") or "IDLE")
        current = player.get("currentNodeId")

        if player.get("delivered") or state in {"DELIVERED", "RETIRED"}:
            self.last_reason = "already delivered or retired"
            return None

        if state in {"PROCESSING", "VERIFYING", "RESTING", "FORCED_PASSING", "CONTESTING"}:
            self.last_reason = f"state {state} should continue without main action"
            return None

        if state == "MOVING":
            horse_action = self._use_horse_if_beneficial(context, snapshot, include_current_edge=True)
            if horse_action is not None:
                return horse_action
            next_node = player.get("nextNodeId")
            if next_node:
                self.last_reason = f"continue moving to {next_node}"
                return {"action": "MOVE", "targetNodeId": next_node}
            self.last_reason = "moving without nextNodeId"
            return None

        if state == "WAITING":
            next_node = player.get("nextNodeId")
            if next_node:
                self.last_reason = f"continue moving to {next_node}"
                return {"action": "MOVE", "targetNodeId": next_node}
            self.last_reason = "moving without nextNodeId"
            return None

        if current == context.terminal_node_id:
            if player.get("verified"):
                self.last_reason = "verified at terminal, deliver"
                return {"action": "DELIVER"}
            self.last_reason = "terminal without verification, return to gate"
            return self._move_toward(context, snapshot, context.gate_node_id)

        if current == context.gate_node_id and snapshot.phase == "RUSH" and not player.get("verified"):
            return self._verify_gate_action(context, snapshot)

        process_node_task_action = self._claim_process_node_task_before_process(context, snapshot)
        if process_node_task_action is not None:
            return process_node_task_action

        if self._should_yield_fixed_process(context, snapshot):
            return None

        process_action = self._process_current_node(context, snapshot)
        if process_action is not None:
            return process_action

        ice_box_action = self._use_ice_box_if_beneficial(context, snapshot)
        if ice_box_action is not None:
            return ice_box_action

        threshold_task_action = self._claim_current_threshold_task_before_dynamic_endgame(context, snapshot)
        if threshold_task_action is not None:
            return threshold_task_action

        bonus_task_action = self._claim_current_bonus_task_before_dynamic_endgame(context, snapshot)
        if bonus_task_action is not None:
            return bonus_task_action

        if self._should_go_endgame(context, snapshot):
            horse_action = self._use_horse_if_beneficial(context, snapshot, include_current_edge=False)
            if horse_action is not None:
                return horse_action
            target = context.terminal_node_id if player.get("verified") else context.gate_node_id
            self.last_reason = f"endgame lock target {target}"
            return self._move_toward(context, snapshot, target)

        task_action = self._claim_current_task(context, snapshot)
        if task_action is not None:
            return task_action

        resource_action = self._claim_current_resource(context, snapshot)
        if resource_action is not None:
            return resource_action

        horse_action = self._use_horse_if_beneficial(context, snapshot, include_current_edge=False)
        if horse_action is not None:
            return horse_action

        target = self._choose_destination(context, snapshot)
        if target:
            return self._move_toward(context, snapshot, target)
        self.last_reason = "no safe target"
        return None

    def _process_current_node(self, context: GameContext, snapshot: GameSnapshot) -> dict[str, Any] | None:
        current = snapshot.self_player.get("currentNodeId")
        node = snapshot.nodes_by_id.get(str(current), {})
        if not current or current in self.memory.completed_process_nodes:
            return None
        process_type = node.get("processType")
        process_round = int(node.get("processRound") or 0)
        if process_type and process_round > 0 and current not in {context.gate_node_id, context.terminal_node_id}:
            self.last_reason = f"process node {current}"
            return {"action": "PROCESS", "targetNodeId": str(current)}
        return None

    def _verify_gate_action(self, context: GameContext, snapshot: GameSnapshot) -> dict[str, Any]:
        if self._can_bind_break_order_to_verify(snapshot):
            self.last_reason = "rush gate verification with BREAK_ORDER"
            return {
                "action": "VERIFY_GATE",
                "targetNodeId": context.gate_node_id,
                "rushTactic": "BREAK_ORDER",
            }
        self.last_reason = "rush gate verification"
        return {"action": "VERIFY_GATE"}

    def _can_bind_break_order_to_verify(self, snapshot: GameSnapshot) -> bool:
        player = snapshot.self_player
        if int(player.get("rushTacticUsedCount") or 0) > 0:
            return False
        return int(player.get("badFruit") or 0) >= BREAK_ORDER_BAD_FRUIT_COST

    def _claim_process_node_task_before_process(
        self, context: GameContext, snapshot: GameSnapshot
    ) -> dict[str, Any] | None:
        current = snapshot.self_player.get("currentNodeId")
        if not current:
            return None
        current_id = str(current)
        if current_id in self.memory.completed_process_nodes:
            return None
        if current_id in {context.gate_node_id, context.terminal_node_id}:
            return None
        node = snapshot.nodes_by_id.get(current_id, {})
        process_round = int(node.get("processRound") or 0)
        if not node.get("processType") or process_round <= 0:
            return None
        if not self._opponent_can_contest_current_node_task(snapshot, current_id):
            return None

        for task in sorted(snapshot.tasks, key=self._task_sort_key):
            if str(task.get("nodeId")) != current_id:
                continue
            if not self._task_available_for_self(context, task, snapshot.self_player):
                continue
            if self._task_waiting_for_fixed_process(task, current_id):
                continue
            if not self._has_endgame_slack_for_process_node_task(context, snapshot, node, task):
                continue
            self.last_reason = f"claim process-node task {task.get('taskId')} before fixed process"
            return {"action": "CLAIM_TASK", "taskId": task["taskId"]}
        return None

    def _opponent_can_contest_current_node_task(self, snapshot: GameSnapshot, current_id: str) -> bool:
        opponent = snapshot.opponent_player or {}
        if str(opponent.get("currentNodeId") or "") != current_id:
            return False
        opponent_state = str(opponent.get("state") or "IDLE")
        return not opponent.get("delivered") and opponent_state not in {"DELIVERED", "RETIRED", "MOVING"}

    def _task_waiting_for_fixed_process(self, task: dict[str, Any], current_id: str) -> bool:
        if current_id in self.memory.completed_process_nodes:
            return False
        task_id = str(task.get("taskId") or "")
        if task_id and task_id in self.memory.process_required_task_ids:
            return True
        return current_id in self.memory.process_required_task_nodes

    def _has_endgame_slack_for_process_node_task(
        self,
        context: GameContext,
        snapshot: GameSnapshot,
        node: dict[str, Any],
        task: dict[str, Any],
    ) -> bool:
        task_rounds = int(task.get("processRound") or 0)
        expire_round = int(task.get("expireRound") or 0)
        if expire_round and snapshot.round_no + task_rounds > expire_round:
            return False
        if not self._should_go_endgame(context, snapshot):
            return True
        if snapshot.phase == "RUSH":
            return False

        current = str(snapshot.self_player.get("currentNodeId") or "")
        remaining_rounds = context.duration_round - snapshot.round_no
        if remaining_rounds <= 0:
            return False
        fixed_process_rounds = int(node.get("processRound") or 0)
        travel_to_gate = self._estimated_travel_rounds(context, snapshot, current, context.gate_node_id)
        travel_to_terminal = self._estimated_travel_rounds(context, snapshot, context.gate_node_id, context.terminal_node_id)
        if travel_to_gate is None or travel_to_terminal is None:
            return False
        required_rounds = (
            task_rounds
            + fixed_process_rounds
            + travel_to_gate
            + self._gate_verify_rounds(context, snapshot)
            + travel_to_terminal
            + 1
        )
        return remaining_rounds >= required_rounds + ENDGAME_TASK_SAFETY_MARGIN_ROUNDS

    def _estimated_travel_rounds(
        self, context: GameContext, snapshot: GameSnapshot, start: str, target: str
    ) -> int | None:
        path = context.graph.shortest_path(start, target, blocked=self._blocked_nodes(context, snapshot))
        if not path:
            path = context.graph.shortest_path(start, target)
        cost = context.graph.path_cost(path)
        if cost is None:
            return None
        return ceil(cost / ROUND_MS)

    def _estimated_delivery_closure_rounds(
        self,
        context: GameContext,
        snapshot: GameSnapshot,
        start: str,
        *,
        assumed_completed_process_nodes: set[str] | None = None,
    ) -> int | None:
        player = snapshot.self_player
        completed = set(self.memory.completed_process_nodes)
        completed.update(assumed_completed_process_nodes or set())

        if player.get("verified"):
            terminal_path = self._path_to(context, snapshot, start, context.terminal_node_id)
            if not terminal_path:
                return None
            terminal_rounds = self._path_rounds(context, snapshot, terminal_path, completed)
            if terminal_rounds is None:
                return None
            return terminal_rounds + 1

        gate_path = self._path_to(context, snapshot, start, context.gate_node_id)
        terminal_path = self._path_to(context, snapshot, context.gate_node_id, context.terminal_node_id)
        if not gate_path or not terminal_path:
            return None
        gate_rounds = self._path_rounds(context, snapshot, gate_path, completed)
        terminal_rounds = self._path_rounds(context, snapshot, terminal_path, completed)
        if gate_rounds is None or terminal_rounds is None:
            return None
        return gate_rounds + self._gate_verify_rounds(context, snapshot) + terminal_rounds + 1

    def _path_to(
        self, context: GameContext, snapshot: GameSnapshot, start: str, target: str
    ) -> list[str]:
        path = context.graph.shortest_path(start, target, blocked=self._blocked_nodes(context, snapshot))
        if not path:
            path = context.graph.shortest_path(start, target)
        return path

    def _path_rounds(
        self,
        context: GameContext,
        snapshot: GameSnapshot,
        path: list[str],
        completed_process_nodes: set[str],
    ) -> int | None:
        cost = context.graph.path_cost(path)
        if cost is None:
            return None
        process_rounds = 0
        for node_id in path:
            if node_id in {context.gate_node_id, context.terminal_node_id}:
                continue
            if node_id in completed_process_nodes:
                continue
            node = snapshot.nodes_by_id.get(node_id, {})
            process_round = int(node.get("processRound") or 0)
            if node.get("processType") and process_round > 0:
                process_rounds += process_round
        return ceil(cost / ROUND_MS) + process_rounds

    def _gate_verify_rounds(self, context: GameContext, snapshot: GameSnapshot) -> int:
        gate = snapshot.nodes_by_id.get(context.gate_node_id, {})
        return int(gate.get("processRound") or DEFAULT_GATE_VERIFY_ROUNDS)

    def _use_ice_box_if_beneficial(self, context: GameContext, snapshot: GameSnapshot) -> dict[str, Any] | None:
        player = snapshot.self_player
        if snapshot.phase == "RUSH":
            return None
        current = str(player.get("currentNodeId") or "")
        if current in {context.gate_node_id, context.terminal_node_id}:
            return None
        resources = player.get("resources") or {}
        if int(resources.get("ICE_BOX") or 0) <= 0:
            return None
        freshness = float(player.get("freshness") or 0)
        if freshness <= 0 or freshness >= ICE_BOX_USE_FRESHNESS_LIMIT:
            return None
        if not self._should_go_endgame(context, snapshot):
            return None
        self.last_reason = f"use ICE_BOX before endgame at freshness {freshness:g}"
        return {"action": "USE_RESOURCE", "resourceType": "ICE_BOX"}

    def _use_horse_if_beneficial(
        self, context: GameContext, snapshot: GameSnapshot, *, include_current_edge: bool
    ) -> dict[str, Any] | None:
        player = snapshot.self_player
        current = str(player.get("currentNodeId") or "")
        if not current or current in {context.gate_node_id, context.terminal_node_id}:
            return None
        resource_type = self._choose_horse_resource(player)
        if resource_type is None:
            return None
        if self._has_speed_buff(player):
            return None
        if self._nearest_task_needs_horse_resource(context, snapshot):
            return None
        if not self._has_meaningful_horse_travel_ahead(context, snapshot, include_current_edge=include_current_edge):
            return None
        self.last_reason = f"use {resource_type} before long movement"
        return {"action": "USE_RESOURCE", "resourceType": resource_type}

    def _choose_horse_resource(self, player: dict[str, Any]) -> str | None:
        resources = player.get("resources") or {}
        for resource_type in HORSE_RESOURCES:
            if self._resource_count(resources, resource_type) > 0:
                return resource_type
        return None

    @staticmethod
    def _resource_count(resources: dict[str, Any], resource_type: str) -> int:
        try:
            return int(resources.get(resource_type) or 0)
        except (TypeError, ValueError):
            return 0

    def _has_speed_buff(self, player: dict[str, Any]) -> bool:
        for buff in player.get("buffs") or []:
            buff_type = str(buff.get("type") or buff.get("buffType") or "").upper()
            if buff_type in SPEED_BUFF_TYPES:
                return True
        return False

    def _has_meaningful_horse_travel_ahead(
        self, context: GameContext, snapshot: GameSnapshot, *, include_current_edge: bool
    ) -> bool:
        player = snapshot.self_player
        travel_rounds = 0
        start_node = str(player.get("currentNodeId") or "")
        if include_current_edge:
            remaining = self._current_edge_remaining_rounds(player)
            if remaining is not None:
                travel_rounds += remaining
            next_node = player.get("nextNodeId")
            if next_node:
                start_node = str(next_node)

        target = self._horse_travel_target(context, snapshot)
        if not start_node or not target:
            return travel_rounds >= MIN_HORSE_TRAVEL_ROUNDS
        if start_node != target:
            estimated = self._estimated_travel_rounds(context, snapshot, start_node, target)
            if estimated is not None:
                travel_rounds += estimated
        return travel_rounds >= MIN_HORSE_TRAVEL_ROUNDS

    def _horse_travel_target(self, context: GameContext, snapshot: GameSnapshot) -> str | None:
        player = snapshot.self_player
        if self._should_go_endgame(context, snapshot) or int(player.get("taskScore") or 0) >= 90:
            return context.terminal_node_id if player.get("verified") else context.gate_node_id
        return self._nearest_task_node(context, snapshot) or context.gate_node_id

    def _nearest_task_needs_horse_resource(self, context: GameContext, snapshot: GameSnapshot) -> bool:
        player = snapshot.self_player
        if self._should_go_endgame(context, snapshot) or int(player.get("taskScore") or 0) >= 90:
            return False
        task = self._nearest_task(context, snapshot)
        return task is not None and self._task_requires_horse_resource(context, task)

    def _task_requires_horse_resource(self, context: GameContext, task: dict[str, Any]) -> bool:
        required = self._task_required_resources(context, task)
        return any(str(resource_type) in HORSE_RESOURCES for resource_type in required)

    def _task_requirements_met(
        self, context: GameContext, task: dict[str, Any], player: dict[str, Any] | None
    ) -> bool:
        if player is None:
            return True
        resources = player.get("resources") or {}
        for resource_type in self._task_required_resources(context, task):
            options = self._resource_options_for_requirement(context, task, str(resource_type))
            if not any(self._resource_count(resources, option) > 0 for option in options):
                return False
        return True

    def _task_required_resources(self, context: GameContext, task: dict[str, Any]) -> list[Any]:
        required = task.get("requiredResourceTypes")
        if required is None:
            required = self._task_template_required_resources(context, task)
        if isinstance(required, str):
            return [required]
        return list(required or [])

    @staticmethod
    def _task_template_required_resources(context: GameContext, task: dict[str, Any]) -> list[Any]:
        template_id = task.get("taskTemplateId")
        if not template_id:
            return []
        for template in context.raw_start.get("taskTemplates") or []:
            if str(template.get("taskTemplateId")) == str(template_id):
                return list(template.get("requiredResourceTypes") or [])
        return []

    def _resource_options_for_requirement(
        self, context: GameContext, task: dict[str, Any], resource_type: str
    ) -> tuple[str, ...]:
        if resource_type == "FAST_HORSE" and self._is_horse_transfer_task(context, task):
            return HORSE_RESOURCES
        return (resource_type,)

    def _is_horse_transfer_task(self, context: GameContext, task: dict[str, Any]) -> bool:
        return self._task_process_type(context, task) == "HORSE_TRANSFER"

    def _task_process_type(self, context: GameContext, task: dict[str, Any]) -> str:
        process_type = task.get("processType")
        if process_type:
            return str(process_type).upper()
        template_id = task.get("taskTemplateId")
        if not template_id:
            return ""
        for template in context.raw_start.get("taskTemplates") or []:
            if str(template.get("taskTemplateId")) == str(template_id):
                return str(template.get("processType") or "").upper()
        return ""

    @staticmethod
    def _current_edge_remaining_rounds(player: dict[str, Any]) -> int | None:
        total_ms = int(player.get("edgeTotalMs") or 0)
        progress_ms = int(player.get("edgeProgressMs") or 0)
        if total_ms <= 0:
            return None
        return max(0, ceil((total_ms - progress_ms) / ROUND_MS))

    def _should_yield_fixed_process(self, context: GameContext, snapshot: GameSnapshot) -> bool:
        current = snapshot.self_player.get("currentNodeId")
        node = snapshot.nodes_by_id.get(str(current), {})
        if not current or current in self.memory.completed_process_nodes:
            return False
        process_type = node.get("processType")
        process_round = int(node.get("processRound") or 0)
        if not process_type or process_round <= 0 or current in {context.gate_node_id, context.terminal_node_id}:
            self._clear_process_yield(str(current))
            return False

        opponent = snapshot.opponent_player or {}
        if str(opponent.get("currentNodeId") or "") != str(current):
            self._clear_process_yield(str(current))
            return False
        opponent_state = str(opponent.get("state") or "IDLE")
        if opponent.get("delivered") or opponent_state in {"DELIVERED", "RETIRED", "MOVING"}:
            self._clear_process_yield(str(current))
            return False
        current_key = str(current)
        loses_tie = self._loses_process_tie(context.player_id, opponent.get("playerId"))
        contested_count = self.memory.process_contest_counts.get(current_key, 0)
        should_yield = (not loses_tie) if contested_count > 0 else loses_tie
        if not should_yield:
            self._clear_process_yield(str(current))
            return False

        if opponent_state == "IDLE":
            yielded = self.memory.process_idle_yield_counts.get(current_key, 0)
            if yielded < IDLE_PROCESS_YIELD_LIMIT:
                self.memory.process_idle_yield_counts[current_key] = yielded + 1
                if contested_count > 0:
                    self.last_reason = (
                        f"back off process node {current} after {contested_count} contest(s) "
                        f"with opponent {opponent.get('playerId')}"
                    )
                else:
                    self.last_reason = f"yield process node {current} to opponent {opponent.get('playerId')}"
                return True
            return False

        if opponent_state in FIXED_PROCESS_BUSY_STATES:
            if contested_count > 0:
                self.last_reason = (
                    f"wait after process contest for opponent {opponent.get('playerId')} at node {current}"
                )
            else:
                self.last_reason = f"wait for opponent {opponent.get('playerId')} at process node {current}"
            return True

        self._clear_process_yield(current_key)
        return False

    def _clear_process_yield(self, node_id: str) -> None:
        if node_id:
            self.memory.process_idle_yield_counts.pop(node_id, None)

    @classmethod
    def _loses_process_tie(cls, self_player_id: Any, opponent_player_id: Any) -> bool:
        if opponent_player_id is None:
            return False
        return cls._player_tie_key(self_player_id) < cls._player_tie_key(opponent_player_id)

    @staticmethod
    def _player_tie_key(player_id: Any) -> tuple[int, int | str]:
        text = str(player_id)
        if text.isdigit():
            return (0, int(text))
        return (1, text)

    def _claim_current_task(self, context: GameContext, snapshot: GameSnapshot) -> dict[str, Any] | None:
        current = snapshot.self_player.get("currentNodeId")
        if not current:
            return None
        for task in sorted(snapshot.tasks, key=self._task_sort_key):
            if not self._task_available_for_self(context, task, snapshot.self_player):
                continue
            if str(task.get("nodeId")) == str(current):
                if not self._has_endgame_slack_for_task(context, snapshot, task):
                    continue
                self.last_reason = f"claim current task {task.get('taskId')}"
                return {"action": "CLAIM_TASK", "taskId": task["taskId"]}
        return None

    def _claim_current_threshold_task_before_dynamic_endgame(
        self, context: GameContext, snapshot: GameSnapshot
    ) -> dict[str, Any] | None:
        if snapshot.phase == "RUSH" or snapshot.round_no >= self._hard_endgame_round(context):
            return None
        if not self._delivery_closure_is_tight(context, snapshot):
            return None
        player = snapshot.self_player
        task_score = int(player.get("taskScore") or 0)
        if task_score >= TASK_SCORE_TARGET:
            return None
        current = player.get("currentNodeId")
        if not current:
            return None
        current_id = str(current)

        for task in sorted(snapshot.tasks, key=self._task_sort_key):
            if str(task.get("nodeId")) != current_id:
                continue
            if task_score + int(task.get("score") or 0) < TASK_SCORE_TARGET:
                continue
            if not self._task_available_for_self(context, task, player):
                continue
            if not self._has_endgame_slack_for_task(context, snapshot, task):
                continue
            self.last_reason = f"claim threshold task {task.get('taskId')} before dynamic endgame"
            return {"action": "CLAIM_TASK", "taskId": task["taskId"]}
        return None

    def _claim_current_bonus_task_before_dynamic_endgame(
        self, context: GameContext, snapshot: GameSnapshot
    ) -> dict[str, Any] | None:
        if snapshot.phase == "RUSH" or snapshot.round_no >= self._hard_endgame_round(context):
            return None
        if not self._delivery_closure_is_tight(context, snapshot):
            return None
        player = snapshot.self_player
        if int(player.get("taskScore") or 0) < TASK_SCORE_TARGET:
            return None
        current = player.get("currentNodeId")
        if not current:
            return None
        current_id = str(current)

        for task in sorted(snapshot.tasks, key=self._task_sort_key):
            if str(task.get("nodeId")) != current_id:
                continue
            if not self._task_available_for_self(context, task, player):
                continue
            if not self._has_endgame_slack_for_task(context, snapshot, task):
                continue
            self.last_reason = f"claim current bonus task {task.get('taskId')} before dynamic endgame"
            return {"action": "CLAIM_TASK", "taskId": task["taskId"]}
        return None

    def _claim_current_resource(self, context: GameContext, snapshot: GameSnapshot) -> dict[str, Any] | None:
        current = snapshot.self_player.get("currentNodeId")
        current_id = "" if current is None else str(current)
        node = snapshot.nodes_by_id.get(current_id, {})
        stock = node.get("resourceStock") or {}
        contested = self._opponent_claiming_resources_at_current(snapshot, current)
        if current_id and current_id in self.memory.contested_resource_nodes:
            self.last_reason = f"skip previously contested resources at {current}"
            return None
        for resource_type in RESOURCE_PRIORITY:
            if current_id and (current_id, resource_type) in self.memory.contested_resources:
                continue
            if int(stock.get(resource_type) or 0) > 0:
                if resource_type in contested:
                    continue
                if not self._resource_has_score_or_tempo_value(context, snapshot, current_id, resource_type):
                    continue
                self.last_reason = f"claim resource {resource_type} at {current}"
                return {"action": "CLAIM_RESOURCE", "targetNodeId": current_id, "resourceType": resource_type}
        if contested:
            self.last_reason = f"skip contested resources at {current}: {','.join(sorted(contested))}"
        return None

    def _resource_has_score_or_tempo_value(
        self, context: GameContext, snapshot: GameSnapshot, current: str, resource_type: str
    ) -> bool:
        if resource_type in ALWAYS_CLAIM_RESOURCE_TYPES:
            return True
        return self._resource_unlocks_available_task(context, snapshot, current, resource_type)

    def _resource_unlocks_available_task(
        self, context: GameContext, snapshot: GameSnapshot, current: str, resource_type: str
    ) -> bool:
        if not current:
            return False
        player = snapshot.self_player
        resources = player.get("resources") or {}
        blocked = self._blocked_nodes(context, snapshot)
        for task in sorted(snapshot.tasks, key=self._task_sort_key):
            if not self._task_available_for_self(context, task, player, require_resources=False):
                continue
            if self._task_available_for_self(context, task, player):
                continue
            if not self._task_missing_resource_options_include(context, task, resources, resource_type):
                continue
            node_id = str(task.get("nodeId") or "")
            if not node_id:
                continue
            if node_id == current or context.graph.shortest_path(current, node_id, blocked=blocked):
                return True
        return False

    def _task_missing_resource_options_include(
        self, context: GameContext, task: dict[str, Any], resources: dict[str, Any], resource_type: str
    ) -> bool:
        for required in self._task_required_resources(context, task):
            options = self._resource_options_for_requirement(context, task, str(required))
            if any(self._resource_count(resources, option) > 0 for option in options):
                continue
            if resource_type in options:
                return True
        return False

    def _opponent_claiming_resources_at_current(self, snapshot: GameSnapshot, current: Any) -> set[str]:
        if current is None:
            return set()
        opponent = snapshot.opponent_player or {}
        if str(opponent.get("currentNodeId") or "") != str(current):
            return set()
        process = opponent.get("currentProcess") or {}
        if str(process.get("action") or "").upper() != "CLAIM_RESOURCE":
            return set()
        target_node = process.get("targetNodeId") or self._resource_node_from_object_key(process.get("objectKey"))
        if target_node is not None and str(target_node) != str(current):
            return set()
        resource_type = process.get("resourceType") or self._resource_type_from_object_key(process.get("objectKey"))
        if not resource_type:
            return set()
        return {str(resource_type)}

    @staticmethod
    def _resource_node_from_object_key(object_key: Any) -> str | None:
        parts = str(object_key or "").split(":")
        if len(parts) >= 3 and parts[0] == "RESOURCE":
            return parts[1]
        return None

    @staticmethod
    def _resource_type_from_object_key(object_key: Any) -> str | None:
        parts = str(object_key or "").split(":")
        if len(parts) >= 3 and parts[0] == "RESOURCE":
            return parts[2]
        return None

    def _choose_destination(self, context: GameContext, snapshot: GameSnapshot) -> str | None:
        player = snapshot.self_player
        task_score = int(player.get("taskScore") or 0)
        if self._should_go_endgame(context, snapshot):
            return context.terminal_node_id if player.get("verified") else context.gate_node_id
        target = self._nearest_task_node(context, snapshot)
        if target:
            waypoint = self._bonus_task_waypoint_before_destination(context, snapshot, target)
            if waypoint:
                self.last_reason = f"detour to bonus task node {waypoint} before {target}"
                return waypoint
            if task_score < TASK_SCORE_TARGET:
                self.last_reason = f"go to task node {target}"
            else:
                self.last_reason = f"go to bonus task node {target}"
            return target
        target = context.terminal_node_id if player.get("verified") else context.gate_node_id
        self.last_reason = f"default endgame target {target}"
        return target

    def _bonus_task_waypoint_before_destination(
        self, context: GameContext, snapshot: GameSnapshot, destination: str
    ) -> str | None:
        current = str(snapshot.self_player.get("currentNodeId") or "")
        if not current or not destination or current == destination:
            return None
        if current not in self.memory.completed_process_nodes:
            return None
        blocked = self._blocked_nodes(context, snapshot)
        direct_path = self._path_to(context, snapshot, current, destination)
        if not direct_path:
            return None
        direct_rounds = self._path_rounds(context, snapshot, direct_path, self.memory.completed_process_nodes)
        if direct_rounds is None:
            return None

        best_node: str | None = None
        best_key: tuple[int, int, int] | None = None
        for task in sorted(snapshot.tasks, key=self._task_sort_key):
            score = int(task.get("score") or 0)
            if score < BONUS_TASK_MIN_SCORE:
                continue
            if not self._task_routeable_for_self(context, snapshot, task):
                continue
            if not self._has_endgame_slack_for_task(context, snapshot, task):
                continue
            node_id = str(task.get("nodeId") or "")
            if not node_id or node_id in {current, destination} or node_id in blocked:
                continue
            path_to_task = self._path_to(context, snapshot, current, node_id)
            path_to_destination = self._path_to(context, snapshot, node_id, destination)
            if not path_to_task or not path_to_destination:
                continue
            if current in path_to_destination[1:]:
                continue
            to_task_rounds = self._path_rounds(context, snapshot, path_to_task, self.memory.completed_process_nodes)
            to_destination_rounds = self._path_rounds(
                context, snapshot, path_to_destination, self.memory.completed_process_nodes
            )
            if to_task_rounds is None or to_destination_rounds is None:
                continue
            task_rounds = int(task.get("processRound") or 0)
            detour_rounds = to_task_rounds + task_rounds + to_destination_rounds - direct_rounds
            if detour_rounds < 0 or detour_rounds > BONUS_TASK_MAX_DETOUR_ROUNDS:
                continue
            key = (score, -detour_rounds, -to_task_rounds)
            if best_key is None or key > best_key or (key == best_key and (best_node is None or node_id < best_node)):
                best_key = key
                best_node = node_id
        return best_node

    def _nearest_task_node(self, context: GameContext, snapshot: GameSnapshot) -> str | None:
        current = str(snapshot.self_player.get("currentNodeId") or "")
        if not current:
            return None
        blocked = self._blocked_nodes(context, snapshot)
        best_node: str | None = None
        best_key: tuple[int, int] | None = None

        for task in sorted(snapshot.tasks, key=self._task_sort_key):
            if not self._task_routeable_for_self(context, snapshot, task):
                continue
            if not self._has_endgame_slack_for_task(context, snapshot, task):
                continue
            node_id = str(task.get("nodeId") or "")
            if not node_id or node_id in blocked:
                continue
            path = context.graph.shortest_path(current, node_id, blocked=blocked)
            if not path:
                continue
            travel_rounds = self._path_rounds(context, snapshot, path, self.memory.completed_process_nodes)
            if travel_rounds is None:
                continue
            cluster_score = self._task_cluster_score(context, snapshot, node_id, blocked)
            if cluster_score <= 0:
                continue
            key = (cluster_score, -travel_rounds)
            if best_key is None or key > best_key or (key == best_key and (best_node is None or node_id < best_node)):
                best_key = key
                best_node = node_id
        return best_node

    def _task_cluster_score(
        self, context: GameContext, snapshot: GameSnapshot, anchor_node_id: str, blocked: set[str]
    ) -> int:
        score = 0
        current = str(snapshot.self_player.get("currentNodeId") or "")
        for task in sorted(snapshot.tasks, key=self._task_sort_key):
            if not self._task_routeable_for_self(context, snapshot, task):
                continue
            if not self._has_endgame_slack_for_task(context, snapshot, task):
                continue
            node_id = str(task.get("nodeId") or "")
            if not node_id or node_id in blocked:
                continue
            if node_id != anchor_node_id:
                followup_blocked = set(blocked)
                if current and current != anchor_node_id:
                    followup_blocked.add(current)
                path = context.graph.shortest_path(anchor_node_id, node_id, blocked=followup_blocked)
                if not path:
                    continue
                travel_rounds = self._path_rounds(context, snapshot, path, self.memory.completed_process_nodes)
                if travel_rounds is None or travel_rounds > TASK_CLUSTER_LOOKAHEAD_ROUNDS:
                    continue
            score += int(task.get("score") or 0)
        return score

    def _nearest_task(self, context: GameContext, snapshot: GameSnapshot) -> dict[str, Any] | None:
        current = snapshot.self_player.get("currentNodeId")
        blocked = self._blocked_nodes(context, snapshot)
        best_path: list[str] = []
        best_task: dict[str, Any] | None = None
        for task in sorted(snapshot.tasks, key=self._task_sort_key):
            if not self._task_routeable_for_self(context, snapshot, task):
                continue
            node_id = str(task.get("nodeId") or "")
            if not node_id or node_id in blocked:
                continue
            path = context.graph.shortest_path(str(current), node_id, blocked=blocked)
            if path and (not best_path or len(path) < len(best_path)):
                if not self._has_endgame_slack_for_task(context, snapshot, task):
                    continue
                best_path = path
                best_task = task
        return best_task

    def _task_routeable_for_self(
        self, context: GameContext, snapshot: GameSnapshot, task: dict[str, Any]
    ) -> bool:
        if self._task_available_for_self(context, task, snapshot.self_player):
            return True
        if not self._task_available_for_self(context, task, snapshot.self_player, require_resources=False):
            return False
        return self._missing_task_resources_available_at_task_node(context, snapshot, task)

    def _has_endgame_slack_for_task(
        self, context: GameContext, snapshot: GameSnapshot, task: dict[str, Any]
    ) -> bool:
        current = str(snapshot.self_player.get("currentNodeId") or "")
        task_node = str(task.get("nodeId") or "")
        if not current or not task_node:
            return False
        if snapshot.phase == "RUSH":
            return False

        path = self._path_to(context, snapshot, current, task_node)
        if not path:
            return False
        travel_rounds = self._path_rounds(context, snapshot, path, self.memory.completed_process_nodes)
        if travel_rounds is None:
            return False

        task_rounds = int(task.get("processRound") or 0)
        resource_rounds = self._missing_task_resource_claim_rounds(context, snapshot, task)
        expire_round = int(task.get("expireRound") or 0)
        if expire_round and snapshot.round_no + travel_rounds + resource_rounds + task_rounds > expire_round:
            return False

        assumed_completed = set(self.memory.completed_process_nodes)
        node = snapshot.nodes_by_id.get(task_node, {})
        if node.get("processType") and int(node.get("processRound") or 0) > 0:
            assumed_completed.add(task_node)
        closure_rounds = self._estimated_delivery_closure_rounds(
            context,
            snapshot,
            task_node,
            assumed_completed_process_nodes=assumed_completed,
        )
        if closure_rounds is None:
            return False

        remaining_rounds = context.duration_round - snapshot.round_no
        required_rounds = travel_rounds + resource_rounds + task_rounds + closure_rounds
        return remaining_rounds >= required_rounds + ENDGAME_TASK_SAFETY_MARGIN_ROUNDS

    def _missing_task_resources_available_at_task_node(
        self, context: GameContext, snapshot: GameSnapshot, task: dict[str, Any]
    ) -> bool:
        node_id = str(task.get("nodeId") or "")
        if not node_id or node_id in self.memory.contested_resource_nodes:
            return False
        node = snapshot.nodes_by_id.get(node_id, {})
        stock = node.get("resourceStock") or {}
        player_resources = snapshot.self_player.get("resources") or {}
        missing = False
        for resource_type in self._task_required_resources(context, task):
            options = self._resource_options_for_requirement(context, task, str(resource_type))
            if any(self._resource_count(player_resources, option) > 0 for option in options):
                continue
            missing = True
            available_options = [
                option
                for option in options
                if (node_id, option) not in self.memory.contested_resources and int(stock.get(option) or 0) > 0
            ]
            if not available_options:
                return False
        return missing

    def _missing_task_resource_claim_rounds(
        self, context: GameContext, snapshot: GameSnapshot, task: dict[str, Any]
    ) -> int:
        node_id = str(task.get("nodeId") or "")
        player_resources = snapshot.self_player.get("resources") or {}
        total = 0
        for resource_type in self._task_required_resources(context, task):
            options = self._resource_options_for_requirement(context, task, str(resource_type))
            if any(self._resource_count(player_resources, option) > 0 for option in options):
                continue
            available_options = [
                option
                for option in options
                if self._resource_count(snapshot.nodes_by_id.get(node_id, {}).get("resourceStock") or {}, option) > 0
            ]
            resource_key = available_options[0] if available_options else options[0]
            total += self._resource_claim_round(context, node_id, resource_key)
        return total

    @staticmethod
    def _resource_claim_round(context: GameContext, node_id: str, resource_type: str) -> int:
        gameplay = (context.raw_start.get("map") or {}).get("gameplay") or {}
        for resource in list(context.raw_start.get("resources") or []) + list(gameplay.get("resources") or []):
            if str(resource.get("nodeId")) == node_id and str(resource.get("resourceType")) == resource_type:
                return int(resource.get("claimRound") or 0)
        return 2

    def _move_toward(self, context: GameContext, snapshot: GameSnapshot, target: str) -> dict[str, Any] | None:
        current = snapshot.self_player.get("currentNodeId")
        if not current:
            self.last_reason = "no current node for movement"
            return None
        if str(current) == target:
            self.last_reason = f"already at {target}"
            return None
        blocked = self._blocked_nodes(context, snapshot)
        path = context.graph.shortest_path(str(current), target, blocked=blocked)
        if not path:
            path = context.graph.shortest_path(str(current), target)
        if len(path) < 2:
            self.last_reason = f"no path from {current} to {target}"
            return None
        next_node = path[1]
        movement_reason = f"move from {current} to {next_node} toward {target}"
        if self.last_reason.startswith(("detour to bonus task node", "go to bonus task node", "go to task node")):
            self.last_reason = f"{self.last_reason}; {movement_reason}"
        else:
            self.last_reason = movement_reason
        return {"action": "MOVE", "targetNodeId": next_node}

    def _blocked_nodes(self, context: GameContext, snapshot: GameSnapshot) -> set[str]:
        blocked: set[str] = set()
        for node_id, node in snapshot.nodes_by_id.items():
            if node.get("hasObstacle"):
                blocked.add(node_id)
                continue
            guard = node.get("guard") or {}
            if guard.get("active") and guard.get("ownerTeamId") != context.team_id:
                blocked.add(node_id)
        blocked.discard(context.gate_node_id)
        blocked.discard(context.terminal_node_id)
        return blocked

    def _should_go_endgame(self, context: GameContext, snapshot: GameSnapshot) -> bool:
        player = snapshot.self_player
        if snapshot.phase == "RUSH":
            return True
        if snapshot.round_no >= self._hard_endgame_round(context):
            return True
        if self._delivery_closure_is_tight(context, snapshot):
            return True
        if float(player.get("freshness") or 0) <= 20:
            return True
        if int(player.get("goodFruit") or 0) <= 5:
            return True
        return False

    @staticmethod
    def _hard_endgame_round(context: GameContext) -> int:
        return min(430, context.duration_round - 120)

    def _delivery_closure_is_tight(self, context: GameContext, snapshot: GameSnapshot) -> bool:
        current = str(snapshot.self_player.get("currentNodeId") or "")
        if not current:
            return False
        closure_rounds = self._estimated_delivery_closure_rounds(context, snapshot, current)
        remaining_rounds = context.duration_round - snapshot.round_no
        return closure_rounds is not None and remaining_rounds <= closure_rounds + DELIVERY_CLOSURE_SAFETY_MARGIN_ROUNDS

    def _task_available_for_self(
        self,
        context: GameContext,
        task: dict[str, Any],
        player: dict[str, Any] | None = None,
        *,
        require_resources: bool = True,
    ) -> bool:
        if not task.get("taskId") or task.get("completed") or task.get("failed"):
            return False
        if task.get("active") is False:
            return False
        if str(task.get("taskId")) in self.memory.completed_tasks:
            return False
        owner = task.get("ownerPlayerId")
        if owner not in (None, 0, "0") and str(owner) != str(context.player_id):
            return False
        protection = task.get("protectionPlayerId")
        if protection not in (None, 0, "0") and str(protection) != str(context.player_id):
            return False
        if require_resources and not self._task_requirements_met(context, task, player):
            return False
        return True

    @staticmethod
    def _task_sort_key(task: dict[str, Any]) -> tuple[int, int, str]:
        return (-int(task.get("score") or 0), int(task.get("expireRound") or 10**9), str(task.get("taskId") or ""))
