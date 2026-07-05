from __future__ import annotations

from math import ceil
from typing import Any

from ..game_state import GameContext, GameMemory, GameSnapshot, same_player_id
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

HORSE_RESOURCE_PRIORITY = ["FAST_HORSE", "SHORT_HORSE"]
HORSE_RESOURCE_TYPES = set(HORSE_RESOURCE_PRIORITY)
HORSE_SPEED_BUFF_TYPES = {"FAST_HORSE", "SHORT_HORSE", "RUSH_SPEED"}
HORSE_TRANSFER_TEMPLATE_IDS = {"T06"}
HORSE_TRANSFER_PROCESS_TYPES = {"HORSE_TRANSFER"}
LOW_VALUE_CONTEST_RESOURCES = {"OFFICIAL_PERMIT", "BOAT_RIGHT"}
LOW_YIELD_OPTIONAL_RESOURCES = {"INTEL", "PASS_TOKEN", "OFFICIAL_PERMIT", "BOAT_RIGHT"}
BASE_TASK_RESOURCE_SCORE = 90
LOW_VALUE_ROUTE_TASK_SCORE = 15
FIXED_PROCESS_BUSY_STATES = {"PROCESSING", "VERIFYING", "RESTING", "CONTESTING"}
IDLE_PROCESS_YIELD_LIMIT = 1
DRAWN_PROCESS_PRESSURE_RETRY_LIMIT = 1
DRAWN_PROCESS_YIELD_LIMIT = 2
DRAWN_TASK_RETRY_LIMIT = 1
EARLY_PROCESS_RACE_TASK_SCORE = 90
DOWNSTREAM_RACE_MIN_TASK_SCORE = 30
DOWNSTREAM_RACE_MAX_TRAVEL_ROUNDS = 80
TASK_GATED_PROCESS_TARGET_SCORE = 105
ENDGAME_TASK_SAFETY_BUFFER_ROUNDS = 10
DELIVERY_SUBMIT_BUFFER_ROUNDS = 2
BREAK_ORDER_BAD_FRUIT_COST = 2
XIAN_GONG_MIN_FRESHNESS = 80
XIAN_GONG_MIN_GOOD_FRUIT = 30
ENDGAME_ICE_BOX_FRESHNESS_CAP = 90.0
SQUAD_ACTION_COSTS = {
    "SQUAD_SCOUT": 1,
    "SQUAD_CLEAR": 2,
    "SQUAD_REINFORCE": 2,
    "SQUAD_WEAKEN": 2,
}
GUARD_ROUTE_NODE_TYPES = {"KEY_PASS", "GATE", "PASS", "MOUNTAIN_PASS", "STRATEGIC_PASS"}
MIN_GOOD_FRUIT_AFTER_GUARD = 20
MIN_GOOD_FRUIT_AFTER_BREAK = 8
GUARD_ACTIVE_AFTER_START_ROUNDS = 5


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
        squad_action = self._squad_action(context, snapshot, main_action)
        if squad_action is not None:
            actions.append(squad_action)
        window_action = self.window_selector.choose(context, snapshot)
        if window_action is not None:
            actions.append(window_action)
        return actions

    def _main_action(self, context: GameContext, snapshot: GameSnapshot) -> dict[str, Any] | None:
        player = snapshot.self_player
        state = str(player.get("state") or "IDLE")
        current = player.get("currentNodeId")

        if self._effective_delivered(player) or state in {"DELIVERED", "RETIRED"}:
            self.last_reason = "already delivered or retired"
            return None

        if state in {"PROCESSING", "VERIFYING", "RESTING", "FORCED_PASSING", "CONTESTING"}:
            self.last_reason = f"state {state} should continue without main action"
            return None

        if state in {"MOVING", "WAITING"}:
            return self._moving_or_waiting_action(context, snapshot)

        if current == context.terminal_node_id:
            if self._effective_verified(player):
                if not self._can_deliver(player):
                    self.last_reason = "terminal but delivery requirements not met"
                    return None
                self.last_reason = "verified at terminal, deliver"
                return {"action": "DELIVER"}
            self.last_reason = "terminal without verification, return to gate"
            return self._move_toward(context, snapshot, context.gate_node_id)

        if current == context.gate_node_id and snapshot.phase == "RUSH" and not self._effective_verified(player):
            return self._gate_verify_action(context, snapshot)

        pre_process_task_action = self._claim_resource_free_current_task_before_process(context, snapshot)
        if pre_process_task_action is not None:
            return pre_process_task_action

        pre_process_resource_task_action = self._claim_required_resource_task_before_process(context, snapshot)
        if pre_process_resource_task_action is not None:
            return pre_process_resource_task_action

        if self._should_yield_drawn_process(context, snapshot):
            return None

        if self._should_yield_fixed_process(context, snapshot):
            return None

        process_action = self._process_current_node(context, snapshot)
        if process_action is not None:
            return process_action

        endgame_task_action = self._claim_safe_current_task_before_endgame(context, snapshot)
        if endgame_task_action is not None:
            return endgame_task_action

        endgame_resource_action = self._use_endgame_resource(context, snapshot)
        if endgame_resource_action is not None:
            return endgame_resource_action

        if self._should_go_endgame(context, snapshot):
            target = context.terminal_node_id if self._effective_verified(player) else context.gate_node_id
            self.last_reason = f"prioritize endgame target {target}"
            return self._move_toward(context, snapshot, target)

        route_resource_action = self._claim_route_enabling_resource_before_task(context, snapshot)
        if route_resource_action is not None:
            return route_resource_action

        task_action = self._claim_current_task(context, snapshot)
        if task_action is not None:
            return task_action

        resource_action = self._claim_current_resource(context, snapshot)
        if resource_action is not None:
            return resource_action

        guard_action = self._set_guard_action(context, snapshot)
        if guard_action is not None:
            return guard_action

        target = self._choose_destination(context, snapshot)
        if target:
            return self._move_toward(context, snapshot, target)
        self.last_reason = "no safe target"
        return None

    def _effective_verified(self, player: dict[str, Any]) -> bool:
        return bool(player.get("verified") or self.memory.gate_verified) and not self.memory.delivery_requires_verification

    def _effective_delivered(self, player: dict[str, Any]) -> bool:
        return bool(player.get("delivered") or self.memory.delivered)

    @staticmethod
    def _can_deliver(player: dict[str, Any]) -> bool:
        return int(player.get("goodFruit") or 0) > 0 and float(player.get("freshness") or 0) > 0

    def _moving_or_waiting_action(self, context: GameContext, snapshot: GameSnapshot) -> dict[str, Any] | None:
        player = snapshot.self_player
        next_node = player.get("nextNodeId")
        if not next_node:
            self.last_reason = "moving without nextNodeId"
            return None
        blocker = self._entry_blocker(context, snapshot, str(next_node), origin=player.get("currentNodeId"))
        if blocker:
            reroute = self._reroute_from_edge_origin(context, snapshot, str(next_node))
            if reroute is not None:
                self.last_reason = f"reroute from edge origin away from blocked {next_node} via {reroute}"
                return {"action": "MOVE", "targetNodeId": reroute}
            self.last_reason = f"pause on edge to {next_node}: {blocker}"
            return {"action": "WAIT"}
        self.last_reason = f"continue moving to {next_node}"
        return {"action": "MOVE", "targetNodeId": str(next_node)}

    def _reroute_from_edge_origin(
        self,
        context: GameContext,
        snapshot: GameSnapshot,
        blocked_target: str,
    ) -> str | None:
        origin = str(snapshot.self_player.get("currentNodeId") or "")
        if not origin:
            return None
        objective = self._route_objective(context, snapshot, excluded={blocked_target})
        if objective is None:
            return None

        hard_blocked = self._hard_blocked_nodes(context, snapshot)
        hard_blocked.add(blocked_target)
        preferred_blocked = set(hard_blocked)
        preferred_blocked.update(self._guard_threat_nodes(context, snapshot))

        best: tuple[int, int, str] | None = None
        for neighbor in context.graph.neighbors(origin):
            candidate = str(neighbor)
            if candidate == blocked_target:
                continue
            if self._entry_blocker(context, snapshot, candidate, origin=origin):
                continue
            if candidate in hard_blocked:
                continue

            path = context.graph.shortest_path(candidate, objective, blocked=preferred_blocked)
            risk_penalty = 0
            if not path:
                path = context.graph.shortest_path(candidate, objective, blocked=hard_blocked)
                risk_penalty = 1
            if not path:
                continue
            rounds = context.graph.path_movement_rounds([origin] + path)
            if rounds is None:
                continue
            key = (risk_penalty, rounds, candidate)
            if best is None or key < best:
                best = key
        return None if best is None else best[2]

    def _squad_action(
        self,
        context: GameContext,
        snapshot: GameSnapshot,
        main_action: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        player = snapshot.self_player
        state = str(player.get("state") or "IDLE")
        if snapshot.phase == "RUSH" or player.get("delivered") or state in {"DELIVERED", "RETIRED"}:
            return None
        available = int(player.get("squadAvailable") or 0)
        if available <= 0:
            return None

        avoided_target = str((main_action or {}).get("targetNodeId") or "")
        moving_target = str(player.get("nextNodeId") or "")
        if moving_target:
            node = snapshot.nodes_by_id.get(moving_target, {})
            if self._enemy_guard_active(context, node) and self._can_spend_squad(available, "SQUAD_WEAKEN"):
                if avoided_target != moving_target or (main_action or {}).get("action") not in {"BREAK_GUARD", "FORCED_PASS"}:
                    return self._squad("SQUAD_WEAKEN", moving_target, main_action)
            if node.get("hasObstacle") and self._can_spend_squad(available, "SQUAD_CLEAR"):
                if avoided_target != moving_target or (main_action or {}).get("action") not in {"CLEAR", "FORCED_PASS"}:
                    return self._squad("SQUAD_CLEAR", moving_target, main_action)

        route_blocker = self._first_route_blocker(context, snapshot)
        if route_blocker:
            node_id, blocker_type = route_blocker
            if blocker_type == "guard" and self._can_spend_squad(available, "SQUAD_WEAKEN"):
                if avoided_target != node_id or (main_action or {}).get("action") not in {"BREAK_GUARD", "FORCED_PASS"}:
                    return self._squad("SQUAD_WEAKEN", node_id, main_action)
            if blocker_type == "obstacle" and self._can_spend_squad(available, "SQUAD_CLEAR"):
                if avoided_target != node_id or (main_action or {}).get("action") not in {"CLEAR", "FORCED_PASS"}:
                    return self._squad("SQUAD_CLEAR", node_id, main_action)

        reinforce_target = self._reinforce_guard_target(context, snapshot)
        if reinforce_target and self._can_spend_squad(available, "SQUAD_REINFORCE"):
            return self._squad("SQUAD_REINFORCE", reinforce_target, main_action)

        scout_target = self._scout_target(context, snapshot)
        if scout_target and self._can_spend_squad(available, "SQUAD_SCOUT"):
            return self._squad("SQUAD_SCOUT", scout_target, main_action)

        return None

    def _squad(self, action: str, target_node_id: str, main_action: dict[str, Any] | None) -> dict[str, Any]:
        if main_action is None:
            self.last_reason = f"{action} target {target_node_id}"
        return {"action": action, "targetNodeId": target_node_id}

    @staticmethod
    def _can_spend_squad(available: int, action: str) -> bool:
        return available >= SQUAD_ACTION_COSTS[action]

    def _first_route_blocker(self, context: GameContext, snapshot: GameSnapshot) -> tuple[str, str] | None:
        player = snapshot.self_player
        current = str(player.get("currentNodeId") or "")
        if not current:
            return None
        targets: list[str] = []
        if int(player.get("taskScore") or 0) < BASE_TASK_RESOURCE_SCORE and snapshot.phase != "RUSH":
            for task in sorted(snapshot.tasks, key=self._task_sort_key):
                if self._task_available_for_self(context, task) and not self._task_claim_skipped(context, snapshot, task):
                    node_id = str(task.get("nodeId") or "")
                    if node_id:
                        targets.append(node_id)
        targets.append(context.terminal_node_id if self._effective_verified(player) else context.gate_node_id)
        for target in targets:
            path = context.graph.shortest_path(current, target)
            for node_id in path[1:]:
                node = snapshot.nodes_by_id.get(str(node_id), {})
                if self._enemy_guard_active(context, node):
                    return str(node_id), "guard"
                if node.get("hasObstacle"):
                    return str(node_id), "obstacle"
        return None

    def _reinforce_guard_target(self, context: GameContext, snapshot: GameSnapshot) -> str | None:
        if int(snapshot.self_player.get("taskScore") or 0) < BASE_TASK_RESOURCE_SCORE:
            return None
        best: tuple[int, str] | None = None
        for node_id, node in snapshot.nodes_by_id.items():
            guard = node.get("guard") or {}
            if not guard.get("active") or guard.get("ownerTeamId") != context.team_id:
                continue
            defense = int(guard.get("defense") or 0)
            max_defense = int(guard.get("maxDefense") or defense)
            if defense <= 0 or defense >= max_defense:
                continue
            if not self._opponent_route_contains(context, snapshot, node_id):
                continue
            key = (defense, node_id)
            if best is None or key < best:
                best = key
        return None if best is None else best[1]

    def _scout_target(self, context: GameContext, snapshot: GameSnapshot) -> str | None:
        if int(snapshot.self_player.get("taskScore") or 0) >= BASE_TASK_RESOURCE_SCORE:
            return None
        current = str(snapshot.self_player.get("currentNodeId") or "")
        for task in sorted(snapshot.tasks, key=self._task_sort_key):
            if not self._task_available_for_self(context, task):
                continue
            node_id = str(task.get("nodeId") or "")
            if not node_id or node_id == current:
                continue
            node = snapshot.nodes_by_id.get(node_id, {})
            if not node or self._has_own_scout(context, node):
                continue
            process_round = int(task.get("processRound") or node.get("processRound") or 0)
            if int(task.get("score") or 0) >= DOWNSTREAM_RACE_MIN_TASK_SCORE or process_round >= 5:
                return node_id
        return None

    def _route_objective(
        self,
        context: GameContext,
        snapshot: GameSnapshot,
        *,
        excluded: set[str] | None = None,
    ) -> str | None:
        excluded = excluded or set()
        player = snapshot.self_player
        if self._should_go_endgame(context, snapshot):
            target = context.terminal_node_id if self._effective_verified(player) else context.gate_node_id
            return None if target in excluded else target
        if int(player.get("taskScore") or 0) < BASE_TASK_RESOURCE_SCORE:
            target = self._nearest_task_node_excluding(context, snapshot, excluded)
            if target:
                return target
        target = context.terminal_node_id if self._effective_verified(player) else context.gate_node_id
        return None if target in excluded else target

    def _nearest_task_node_excluding(
        self,
        context: GameContext,
        snapshot: GameSnapshot,
        excluded: set[str],
    ) -> str | None:
        current = snapshot.self_player.get("currentNodeId")
        blocked = self._blocked_nodes(context, snapshot)
        blocked.update(excluded)
        best_node_id: str | None = None
        best_rounds: int | None = None
        for task in sorted(snapshot.tasks, key=self._task_sort_key):
            if not self._task_available_for_self(context, task):
                continue
            if self._task_claim_skipped(context, snapshot, task):
                continue
            if not self._task_route_viable(context, snapshot, task):
                continue
            node_id = str(task.get("nodeId") or "")
            if not node_id or node_id in blocked:
                continue
            rounds = self._shortest_rounds(context, str(current or ""), node_id, blocked)
            if rounds is None:
                continue
            if not self._can_finish_after_remote_task(context, snapshot, task, node_id, rounds):
                continue
            if best_rounds is None or rounds < best_rounds:
                best_node_id = node_id
                best_rounds = rounds
        return best_node_id

    def _set_guard_action(self, context: GameContext, snapshot: GameSnapshot) -> dict[str, Any] | None:
        player = snapshot.self_player
        if snapshot.phase == "RUSH" or int(player.get("taskScore") or 0) < BASE_TASK_RESOURCE_SCORE:
            return None
        current = str(player.get("currentNodeId") or "")
        if not current or current in {context.start_node_id, context.terminal_node_id}:
            return None
        node = snapshot.nodes_by_id.get(current, {})
        guard = node.get("guard") or {}
        if guard.get("active") or node.get("safeZone") is True:
            return None
        if self._own_active_guard_count(context, snapshot) >= 2:
            return None
        if not self._guard_worth_node(node):
            return None
        if not self._opponent_route_contains(context, snapshot, current):
            return None
        if int(player.get("goodFruit") or 0) <= MIN_GOOD_FRUIT_AFTER_GUARD:
            return None
        action: dict[str, Any] = {"action": "SET_GUARD", "targetNodeId": current}
        if int(player.get("goodFruit") or 0) >= 60:
            action["extraGoodFruit"] = 1
        self.last_reason = f"set guard at route choke {current}"
        return action

    @staticmethod
    def _guard_worth_node(node: dict[str, Any]) -> bool:
        node_type = str(node.get("nodeType") or "").upper()
        return node_type in GUARD_ROUTE_NODE_TYPES or node.get("guardCandidate") is True

    @staticmethod
    def _own_active_guard_count(context: GameContext, snapshot: GameSnapshot) -> int:
        total = 0
        for node in snapshot.nodes_by_id.values():
            guard = node.get("guard") or {}
            if guard.get("active") and guard.get("ownerTeamId") == context.team_id:
                total += 1
        return total

    def _opponent_route_contains(self, context: GameContext, snapshot: GameSnapshot, node_id: str) -> bool:
        opponent = snapshot.opponent_player or {}
        if opponent.get("delivered") or str(opponent.get("state") or "") in {"DELIVERED", "RETIRED"}:
            return False
        start = str(opponent.get("currentNodeId") or "")
        if not start or start == node_id:
            return False
        goal = context.terminal_node_id if opponent.get("verified") else context.gate_node_id
        path = context.graph.shortest_path(start, goal)
        return node_id in path[1:]

    @staticmethod
    def _has_own_scout(context: GameContext, node: dict[str, Any]) -> bool:
        for marker in node.get("scouted") or []:
            if marker.get("teamId") == context.team_id and int(marker.get("remainingTriggers") or 0) > 0:
                return True
        return False

    def _process_current_node(self, context: GameContext, snapshot: GameSnapshot) -> dict[str, Any] | None:
        current = snapshot.self_player.get("currentNodeId")
        node = snapshot.nodes_by_id.get(str(current), {})
        if not current or current in self.memory.completed_process_nodes:
            return None
        if str(current) in self.memory.skipped_process_nodes:
            self.last_reason = f"skip drawn process node {current}"
            return None
        process_type = node.get("processType")
        process_round = int(node.get("processRound") or 0)
        if process_type and process_round > 0 and current not in {context.gate_node_id, context.terminal_node_id}:
            self.last_reason = f"process node {current}"
            return {"action": "PROCESS", "targetNodeId": str(current)}
        return None

    def _claim_resource_free_current_task_before_process(
        self,
        context: GameContext,
        snapshot: GameSnapshot,
    ) -> dict[str, Any] | None:
        if snapshot.phase == "RUSH":
            return None
        current = snapshot.self_player.get("currentNodeId")
        if not current or current in {context.gate_node_id, context.terminal_node_id}:
            return None
        if current in self.memory.completed_process_nodes:
            return None

        node = snapshot.nodes_by_id.get(str(current), {})
        process_type = node.get("processType")
        process_round = int(node.get("processRound") or 0)
        if not process_type or process_round <= 0:
            return None

        for task in self._current_available_tasks(context, snapshot):
            downstream_task = self._downstream_replacement_task_after_process(
                context,
                snapshot,
                task,
                process_round,
            )
            if downstream_task is not None:
                self.last_reason = (
                    f"defer low-value task {task.get('taskId')} for downstream task "
                    f"{downstream_task.get('taskId')}"
                )
                continue
            if self._task_required_resources(context, task):
                continue
            if self._missing_task_resources(context, snapshot, task):
                continue
            if not self._can_finish_after_current_task_with_pending_process(context, snapshot, task, process_round):
                self.last_reason = f"skip pre-process task {task.get('taskId')} due delivery budget"
                continue
            self.last_reason = f"claim current task {task.get('taskId')} before process {current}"
            return {"action": "CLAIM_TASK", "taskId": task["taskId"]}
        return None

    def _claim_required_resource_task_before_process(
        self,
        context: GameContext,
        snapshot: GameSnapshot,
    ) -> dict[str, Any] | None:
        if snapshot.phase == "RUSH" or self._should_go_endgame(context, snapshot):
            return None
        current = snapshot.self_player.get("currentNodeId")
        if not current or current in {context.gate_node_id, context.terminal_node_id}:
            return None
        if current in self.memory.completed_process_nodes or str(current) in self.memory.skipped_process_nodes:
            return None

        node = snapshot.nodes_by_id.get(str(current), {})
        process_type = node.get("processType")
        process_round = int(node.get("processRound") or 0)
        if not process_type or process_round <= 0:
            return None

        for task in self._current_available_tasks(context, snapshot):
            missing_resources = self._missing_task_resources(context, snapshot, task)
            if not missing_resources:
                continue
            if self._should_defer_horse_task_for_downstream_race(
                context,
                snapshot,
                task,
                extra_current_rounds=process_round,
            ):
                downstream_task = self._downstream_resource_free_task_on_endgame_path(
                    context,
                    snapshot,
                    min_score=int(task.get("score") or 0),
                    extra_current_rounds=process_round,
                )
                self.last_reason = (
                    f"defer resource-gated task {task.get('taskId')} before process "
                    f"for downstream task {downstream_task.get('taskId') if downstream_task else 'race'}"
                )
                continue
            resource_rounds = self._remote_task_resource_rounds(context, snapshot, task, str(current))
            if resource_rounds <= 0:
                continue
            if not self._can_finish_after_current_task_with_pending_process(
                context,
                snapshot,
                task,
                process_round + resource_rounds,
            ):
                self.last_reason = f"skip required-resource task {task.get('taskId')} before process due delivery budget"
                continue
            resource_action = self._claim_required_current_resource(
                context,
                snapshot,
                current,
                missing_resources,
                task,
            )
            if resource_action is None:
                continue
            resource_type = str(resource_action.get("resourceType") or "")
            if self._would_start_idle_resource_contest(snapshot, current, resource_type):
                if not self._should_contest_required_horse_resource_for_current_task(
                    context,
                    snapshot,
                    task,
                    resource_type,
                ):
                    self.last_reason = f"skip required resource {resource_type} at {current}: opponent contest risk"
                    continue
                self.last_reason = (
                    f"contest required horse resource {resource_type} for current task "
                    f"{task.get('taskId')} before process {current}"
                )
                return resource_action
            self.last_reason = f"claim required resource {resource_type} for current task {task.get('taskId')} before process {current}"
            return resource_action
        return None

    def _should_contest_required_horse_resource_for_current_task(
        self,
        context: GameContext,
        snapshot: GameSnapshot,
        task: dict[str, Any],
        resource_type: str,
    ) -> bool:
        if resource_type not in HORSE_RESOURCE_TYPES:
            return False
        if not self._task_accepts_horse_resource(context, task):
            return False
        if int(task.get("score") or 0) < DOWNSTREAM_RACE_MIN_TASK_SCORE:
            return False
        return self._ordinary_task_base_score(context, snapshot) < BASE_TASK_RESOURCE_SCORE

    def _downstream_replacement_task_after_process(
        self,
        context: GameContext,
        snapshot: GameSnapshot,
        current_task: dict[str, Any],
        process_rounds: int,
    ) -> dict[str, Any] | None:
        if self._ordinary_task_base_score(context, snapshot) < BASE_TASK_RESOURCE_SCORE:
            return None
        current_task_score = int(current_task.get("score") or 0)
        if current_task_score <= 0 or current_task_score > LOW_VALUE_ROUTE_TASK_SCORE:
            return None
        if self._task_required_resources(context, current_task):
            return None
        if self._missing_task_resources(context, snapshot, current_task):
            return None

        current = str(snapshot.self_player.get("currentNodeId") or "")
        if not current:
            return None
        target = context.terminal_node_id if self._effective_verified(snapshot.self_player) else context.gate_node_id
        blocked = self._blocked_nodes(context, snapshot)
        path = context.graph.shortest_path(current, target, blocked=blocked)
        if not path or len(path) < 2:
            return None

        for task in sorted(snapshot.tasks, key=self._task_sort_key):
            if task is current_task:
                continue
            if int(task.get("score") or 0) <= current_task_score:
                continue
            if not self._task_available_for_self(context, task):
                continue
            if self._task_claim_skipped(context, snapshot, task):
                continue
            if self._missing_task_resources(context, snapshot, task):
                continue
            node_id = str(task.get("nodeId") or "")
            if not node_id or node_id == current or node_id in blocked:
                continue
            if node_id not in path[1:]:
                continue
            node_index = path.index(node_id)
            travel_rounds = context.graph.path_movement_rounds(path[: node_index + 1])
            if travel_rounds is None:
                continue
            if not self._can_finish_after_remote_task(
                context,
                snapshot,
                task,
                node_id,
                process_rounds + travel_rounds,
            ):
                continue
            return task
        return None

    def _gate_verify_action(self, context: GameContext, snapshot: GameSnapshot) -> dict[str, Any]:
        if self._should_bind_break_order_to_gate(snapshot):
            self.last_reason = "rush gate verification with BREAK_ORDER"
            return {
                "action": "VERIFY_GATE",
                "targetNodeId": context.gate_node_id,
                "rushTactic": "BREAK_ORDER",
            }
        self.last_reason = "rush gate verification"
        return {"action": "VERIFY_GATE"}

    @staticmethod
    def _should_bind_break_order_to_gate(snapshot: GameSnapshot) -> bool:
        player = snapshot.self_player
        if int(player.get("rushTacticUsedCount") or 0) > 0:
            return False
        if int(player.get("badFruit") or 0) >= BREAK_ORDER_BAD_FRUIT_COST:
            return True
        return int(player.get("goodFruit") or 0) > 1

    def _should_yield_drawn_process(self, context: GameContext, snapshot: GameSnapshot) -> bool:
        current = snapshot.self_player.get("currentNodeId")
        current_key = str(current or "")
        if not current_key or current_key not in self.memory.skipped_process_nodes:
            return False

        node = snapshot.nodes_by_id.get(current_key, {})
        process_type = node.get("processType")
        process_round = int(node.get("processRound") or 0)
        if not process_type or process_round <= 0 or current_key in {context.gate_node_id, context.terminal_node_id}:
            self._clear_drawn_process(current_key)
            return False

        opponent = snapshot.opponent_player or {}
        opponent_state = str(opponent.get("state") or "IDLE")
        if (
            str(opponent.get("currentNodeId") or "") == current_key
            and opponent_state == "IDLE"
            and not opponent.get("delivered")
            and self._loses_process_tie(context.player_id, opponent.get("playerId"))
        ):
            if self._should_retry_drawn_process_before_yield(context, snapshot, current_key):
                retries = self.memory.drawn_process_retry_counts.get(current_key, 0)
                self.memory.drawn_process_retry_counts[current_key] = retries + 1
                self._clear_drawn_process(current_key)
                return False
            yielded = self.memory.drawn_process_yield_counts.get(current_key, 0)
            if yielded < DRAWN_PROCESS_YIELD_LIMIT:
                self.memory.drawn_process_yield_counts[current_key] = yielded + 1
                self.last_reason = f"yield drawn process node {current_key} to opponent {opponent.get('playerId')}"
                return True

        self._clear_drawn_process(current_key)
        return False

    def _should_retry_drawn_process_before_yield(
        self,
        context: GameContext,
        snapshot: GameSnapshot,
        current_key: str,
    ) -> bool:
        if self.memory.drawn_process_retry_counts.get(current_key, 0) >= DRAWN_PROCESS_PRESSURE_RETRY_LIMIT:
            return False
        if self._ordinary_task_base_score(context, snapshot) >= EARLY_PROCESS_RACE_TASK_SCORE:
            return False
        if self._should_compete_for_task_gated_process(context, snapshot):
            return True
        return self._has_reachable_high_value_task_after_process(context, snapshot)

    def _should_yield_fixed_process(self, context: GameContext, snapshot: GameSnapshot) -> bool:
        current = snapshot.self_player.get("currentNodeId")
        node = snapshot.nodes_by_id.get(str(current), {})
        if not current or current in self.memory.completed_process_nodes:
            return False
        if str(current) in self.memory.skipped_process_nodes:
            self._clear_process_yield(str(current))
            return False
        process_type = node.get("processType")
        process_round = int(node.get("processRound") or 0)
        if not process_type or process_round <= 0 or current in {context.gate_node_id, context.terminal_node_id}:
            self._clear_process_yield(str(current))
            return False

        base_task_score = self._ordinary_task_base_score(context, snapshot)
        compete_for_current_task = self._should_compete_for_task_gated_process(context, snapshot)
        early_desync = base_task_score < EARLY_PROCESS_RACE_TASK_SCORE and not compete_for_current_task
        if base_task_score < EARLY_PROCESS_RACE_TASK_SCORE and compete_for_current_task:
            self._clear_process_yield(str(current))
            return False

        if base_task_score >= EARLY_PROCESS_RACE_TASK_SCORE and compete_for_current_task:
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
        if not self._loses_process_tie(context.player_id, opponent.get("playerId")):
            self._clear_process_yield(str(current))
            return False

        current_key = str(current)
        if opponent_state == "IDLE":
            if self._should_force_terminal_corridor_process(context, snapshot, current_key):
                self._clear_process_yield(current_key)
                return False
            if early_desync and self._has_reachable_high_value_task_after_process(context, snapshot):
                self._clear_process_yield(current_key)
                return False
            yielded = self.memory.process_idle_yield_counts.get(current_key, 0)
            if yielded < IDLE_PROCESS_YIELD_LIMIT:
                self.memory.process_idle_yield_counts[current_key] = yielded + 1
                self.last_reason = f"yield process node {current} to opponent {opponent.get('playerId')}"
                return True
            return False

        if opponent_state in FIXED_PROCESS_BUSY_STATES:
            if early_desync:
                self._clear_process_yield(current_key)
                return False
            if not self._opponent_processing_fixed_node(snapshot, current_key):
                self._clear_process_yield(current_key)
                return False
            self.last_reason = f"wait for opponent {opponent.get('playerId')} at process node {current}"
            return True

        self._clear_process_yield(current_key)
        return False

    @staticmethod
    def _opponent_processing_fixed_node(snapshot: GameSnapshot, current_node_id: str) -> bool:
        opponent = snapshot.opponent_player or {}
        process = opponent.get("currentProcess") or {}
        if str(process.get("action") or "").upper() != "PROCESS":
            return False
        target_node_id = process.get("targetNodeId") or process.get("nodeId")
        if target_node_id is not None and str(target_node_id) == current_node_id:
            return True
        object_key = str(process.get("objectKey") or "")
        return object_key.startswith(f"PROCESS:{current_node_id}:")

    def _should_force_terminal_corridor_process(
        self,
        context: GameContext,
        snapshot: GameSnapshot,
        current_node_id: str,
    ) -> bool:
        if self._ordinary_task_base_score(context, snapshot) < BASE_TASK_RESOURCE_SCORE:
            return False
        if self._should_compete_for_task_gated_process(context, snapshot):
            return False
        if self._has_reachable_high_value_task_after_process(context, snapshot):
            return False

        gameplay = (context.raw_start.get("map") or {}).get("gameplay") or {}
        roles = gameplay.get("roles") or {}
        rush_excluded = {str(node_id) for node_id in roles.get("rushExcludedNodeIds") or []}
        if current_node_id not in rush_excluded:
            return False

        target = context.terminal_node_id if self._effective_verified(snapshot.self_player) else context.gate_node_id
        blocked = self._blocked_nodes(context, snapshot)
        path = context.graph.shortest_path(current_node_id, target, blocked=blocked)
        if not path:
            path = context.graph.shortest_path(current_node_id, target)
        return len(path) >= 2

    def _should_compete_for_task_gated_process(self, context: GameContext, snapshot: GameSnapshot) -> bool:
        if self._ordinary_task_base_score(context, snapshot) >= TASK_GATED_PROCESS_TARGET_SCORE:
            return False
        for task in self._current_available_tasks(context, snapshot):
            if not self._missing_task_resources(context, snapshot, task):
                return True
        return False

    def _has_reachable_high_value_task_after_process(self, context: GameContext, snapshot: GameSnapshot) -> bool:
        current = str(snapshot.self_player.get("currentNodeId") or "")
        if not current:
            return False

        current_node = snapshot.nodes_by_id.get(current) or {}
        current_process_rounds = max(1, int(current_node.get("processRound") or 1))
        blocked = self._blocked_nodes(context, snapshot)
        for task in sorted(snapshot.tasks, key=self._task_sort_key):
            if int(task.get("score") or 0) < DOWNSTREAM_RACE_MIN_TASK_SCORE:
                continue
            if not self._task_available_for_self(context, task):
                continue
            if not self._task_route_viable(context, snapshot, task):
                continue
            node_id = str(task.get("nodeId") or "")
            if not node_id or node_id == current or node_id in blocked:
                continue
            travel_rounds = self._shortest_rounds(context, current, node_id, blocked)
            if travel_rounds is None:
                travel_rounds = self._shortest_rounds(context, current, node_id, set())
            if travel_rounds is None or travel_rounds > DOWNSTREAM_RACE_MAX_TRAVEL_ROUNDS:
                continue
            if self._can_finish_after_remote_task(
                context,
                snapshot,
                task,
                node_id,
                current_process_rounds + travel_rounds,
            ):
                return True
        return False

    def _ordinary_task_base_score(self, context: GameContext, snapshot: GameSnapshot) -> int:
        completed_score = 0
        for task in snapshot.tasks:
            if not task.get("completed"):
                continue
            if str(task.get("ownerPlayerId") or "") != str(context.player_id):
                continue
            completed_score += int(task.get("score") or 0)
        if completed_score:
            return completed_score
        return int(snapshot.self_player.get("taskScore") or 0)

    def _clear_process_yield(self, node_id: str) -> None:
        if node_id:
            self.memory.process_idle_yield_counts.pop(node_id, None)

    def _clear_drawn_process(self, node_id: str) -> None:
        if node_id:
            self.memory.skipped_process_nodes.discard(node_id)
            self.memory.drawn_process_yield_counts.pop(node_id, None)

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

    def _claim_current_task(
        self,
        context: GameContext,
        snapshot: GameSnapshot,
        *,
        allow_required_resource: bool = True,
    ) -> dict[str, Any] | None:
        current = snapshot.self_player.get("currentNodeId")
        if not current:
            return None
        tasks = self._current_available_tasks(context, snapshot)
        for task in tasks:
            missing_resources = self._missing_task_resources(context, snapshot, task)
            if missing_resources:
                if self._should_defer_horse_task_for_downstream_race(context, snapshot, task):
                    downstream_task = self._downstream_resource_free_task_on_endgame_path(
                        context,
                        snapshot,
                        min_score=int(task.get("score") or 0),
                    )
                    self.last_reason = (
                        f"defer resource-gated task {task.get('taskId')} "
                        f"for downstream task {downstream_task.get('taskId') if downstream_task else 'race'}"
                    )
                    continue
                if allow_required_resource:
                    resource_action = self._claim_required_current_resource(
                        context,
                        snapshot,
                        current,
                        missing_resources,
                        task,
                    )
                    if resource_action is not None:
                        return resource_action
                self.last_reason = (
                    f"skip task {task.get('taskId')} missing required resource " + ",".join(missing_resources)
                )
                continue
            if self._should_defer_unfavorable_current_task_contest(context, snapshot, task, tasks):
                self.last_reason = f"defer contested task {task.get('taskId')} for safer current-node alternate"
                continue
            self.last_reason = f"claim current task {task.get('taskId')}"
            return {"action": "CLAIM_TASK", "taskId": task["taskId"]}
        return None

    def _should_defer_unfavorable_current_task_contest(
        self,
        context: GameContext,
        snapshot: GameSnapshot,
        task: dict[str, Any],
        current_tasks: list[dict[str, Any]],
    ) -> bool:
        if not self._has_direct_current_task_alternative(context, snapshot, task, current_tasks):
            return False
        if not self._opponent_idle_at_self_node(snapshot):
            return False
        if not self._task_contestable_by_opponent(context, snapshot, task):
            return False
        if not self._opponent_can_pay_xian_gong(snapshot):
            return False
        if self._should_contest_high_value_task_to_block_opponent_base(context, snapshot, task, current_tasks):
            return False
        return not self._has_task_safe_qiang_xing_counter(context, snapshot, task)

    def _should_contest_high_value_task_to_block_opponent_base(
        self,
        context: GameContext,
        snapshot: GameSnapshot,
        task: dict[str, Any],
        current_tasks: list[dict[str, Any]],
    ) -> bool:
        if self._ordinary_task_base_score(context, snapshot) < BASE_TASK_RESOURCE_SCORE:
            return False
        if self._opponent_ordinary_task_base_score(context, snapshot) >= BASE_TASK_RESOURCE_SCORE:
            return False
        if int(task.get("score") or 0) < DOWNSTREAM_RACE_MIN_TASK_SCORE:
            return False
        if self._missing_task_resources(context, snapshot, task):
            return False
        if not self._can_finish_after_current_task(context, snapshot, task):
            return False

        task_score = int(task.get("score") or 0)
        return any(
            0 < int(alternate.get("score") or 0) <= LOW_VALUE_ROUTE_TASK_SCORE < task_score
            and alternate is not task
            and alternate.get("taskId") != task.get("taskId")
            and not self._missing_task_resources(context, snapshot, alternate)
            for alternate in current_tasks
        )

    def _opponent_ordinary_task_base_score(self, context: GameContext, snapshot: GameSnapshot) -> int:
        opponent = snapshot.opponent_player or {}
        opponent_id = opponent.get("playerId")
        if opponent_id is None:
            opponent_id = context.opponent_player_id
        if opponent_id is None:
            return BASE_TASK_RESOURCE_SCORE

        completed_score = 0
        for task in snapshot.tasks:
            if not task.get("completed"):
                continue
            if str(task.get("ownerPlayerId") or "") != str(opponent_id):
                continue
            completed_score += int(task.get("score") or 0)
        if completed_score:
            return completed_score
        return int(opponent.get("taskScore") or 0)

    def _has_direct_current_task_alternative(
        self,
        context: GameContext,
        snapshot: GameSnapshot,
        task: dict[str, Any],
        current_tasks: list[dict[str, Any]],
    ) -> bool:
        base_score = self._ordinary_task_base_score(context, snapshot)
        task_score = int(task.get("score") or 0)
        for alternate in current_tasks:
            if alternate is task or alternate.get("taskId") == task.get("taskId"):
                continue
            alternate_score = int(alternate.get("score") or 0)
            if alternate_score <= 0 or alternate_score >= task_score:
                continue
            if base_score < BASE_TASK_RESOURCE_SCORE and base_score + alternate_score < BASE_TASK_RESOURCE_SCORE:
                continue
            if self._missing_task_resources(context, snapshot, alternate):
                continue
            return True
        return False

    def _opponent_idle_at_self_node(self, snapshot: GameSnapshot) -> bool:
        current = str(snapshot.self_player.get("currentNodeId") or "")
        opponent = snapshot.opponent_player or {}
        if not current or str(opponent.get("currentNodeId") or "") != current:
            return False
        if opponent.get("delivered"):
            return False
        return str(opponent.get("state") or "IDLE") == "IDLE"

    @staticmethod
    def _task_contestable_by_opponent(
        context: GameContext,
        snapshot: GameSnapshot,
        task: dict[str, Any],
    ) -> bool:
        opponent = snapshot.opponent_player or {}
        opponent_id = opponent.get("playerId")
        if opponent_id is None:
            opponent_id = context.opponent_player_id
        if opponent_id is None:
            return False
        owner = task.get("ownerPlayerId")
        if owner not in (None, 0, "0") and not same_player_id(owner, opponent_id):
            return False
        protection = task.get("protectionPlayerId")
        if protection not in (None, 0, "0") and not same_player_id(protection, opponent_id):
            return False
        return True

    @staticmethod
    def _opponent_can_pay_xian_gong(snapshot: GameSnapshot) -> bool:
        opponent = snapshot.opponent_player or {}
        return (
            float(opponent.get("freshness") or 0) >= XIAN_GONG_MIN_FRESHNESS
            and int(opponent.get("goodFruit") or 0) > XIAN_GONG_MIN_GOOD_FRUIT
        )

    def _has_task_safe_qiang_xing_counter(
        self,
        context: GameContext,
        snapshot: GameSnapshot,
        task: dict[str, Any],
    ) -> bool:
        player = snapshot.self_player
        if self._has_horse_speed_buff(player):
            return True
        horse_count = self._horse_resource_count(player.get("resources") or {})
        if horse_count <= 0:
            return False
        if horse_count == 1 and self._task_accepts_horse_resource(context, task):
            return False
        return True

    @staticmethod
    def _has_horse_speed_buff(player: dict[str, Any]) -> bool:
        return any((buff.get("type") in HORSE_SPEED_BUFF_TYPES) for buff in player.get("buffs") or [])

    @staticmethod
    def _horse_resource_count(resources: dict[str, Any]) -> int:
        return sum(int(resources.get(resource_type) or 0) for resource_type in HORSE_RESOURCE_TYPES)

    def _claim_safe_current_task_before_endgame(
        self,
        context: GameContext,
        snapshot: GameSnapshot,
    ) -> dict[str, Any] | None:
        if not self._should_go_endgame(context, snapshot):
            return None
        if snapshot.phase == "RUSH":
            return None
        player = snapshot.self_player
        if float(player.get("freshness") or 0) <= 20 or int(player.get("goodFruit") or 0) <= 5:
            return None

        task = next(iter(self._current_available_tasks(context, snapshot)), None)
        if task is None:
            return None
        if self._missing_task_resources(context, snapshot, task):
            self.last_reason = f"skip endgame task {task.get('taskId')} missing required resource"
            return None
        if not self._can_finish_after_current_task(context, snapshot, task):
            self.last_reason = f"skip endgame task {task.get('taskId')} due delivery budget"
            return None
        return self._claim_current_task(context, snapshot, allow_required_resource=False)

    def _use_endgame_resource(self, context: GameContext, snapshot: GameSnapshot) -> dict[str, Any] | None:
        if not self._should_go_endgame(context, snapshot):
            return None
        player = snapshot.self_player
        current = player.get("currentNodeId")
        if not current or current in {context.gate_node_id, context.terminal_node_id}:
            return None
        resources = player.get("resources") or {}
        if int(resources.get("ICE_BOX") or 0) <= 0:
            return None
        freshness = float(player.get("freshness") or 0)
        if freshness <= 0 or freshness >= ENDGAME_ICE_BOX_FRESHNESS_CAP:
            return None
        self.last_reason = f"use ICE_BOX before endgame from {current}"
        return {"action": "USE_RESOURCE", "resourceType": "ICE_BOX"}

    def _claim_route_enabling_resource_before_task(
        self,
        context: GameContext,
        snapshot: GameSnapshot,
    ) -> dict[str, Any] | None:
        player = snapshot.self_player
        current = player.get("currentNodeId")
        if snapshot.phase == "RUSH" or not current:
            return None
        if int(player.get("taskScore") or 0) >= 90:
            return None
        if self._has_any_resource(player, HORSE_RESOURCE_TYPES):
            return None

        resource_type = self._available_current_horse_resource(snapshot, current)
        if resource_type is None:
            return None

        target_task = self._nearest_horse_transfer_task(context, snapshot)
        if target_task is None or str(target_task.get("nodeId") or "") == str(current):
            return None

        current_task_score = max(
            (int(task.get("score") or 0) for task in self._current_available_tasks(context, snapshot)),
            default=0,
        )
        target_score = int(target_task.get("score") or 0)
        if current_task_score > target_score:
            return None

        self.last_reason = f"claim route-enabling {resource_type} for task {target_task.get('taskId')}"
        return {"action": "CLAIM_RESOURCE", "targetNodeId": str(current), "resourceType": resource_type}

    def _should_defer_horse_task_for_downstream_race(
        self,
        context: GameContext,
        snapshot: GameSnapshot,
        task: dict[str, Any],
        *,
        extra_current_rounds: int = 0,
    ) -> bool:
        if snapshot.phase == "RUSH" or self._should_go_endgame(context, snapshot):
            return False
        if self._ordinary_task_base_score(context, snapshot) >= BASE_TASK_RESOURCE_SCORE:
            return False
        if not self._task_accepts_horse_resource(context, task):
            return False
        missing_resources = self._missing_task_resources(context, snapshot, task)
        if not any(resource_type in HORSE_RESOURCE_TYPES for resource_type in missing_resources):
            return False
        if int(task.get("score") or 0) < DOWNSTREAM_RACE_MIN_TASK_SCORE:
            return False

        current = str(snapshot.self_player.get("currentNodeId") or "")
        if not current or not self._has_opponent_route_pressure(snapshot, current):
            return False
        if self._should_take_current_horse_resource_against_busy_opponent(snapshot, current):
            return False

        return (
            self._downstream_resource_free_task_on_endgame_path(
                context,
                snapshot,
                min_score=int(task.get("score") or 0),
                extra_current_rounds=extra_current_rounds,
            )
            is not None
        )

    def _should_take_current_horse_resource_against_busy_opponent(
        self,
        snapshot: GameSnapshot,
        current: str,
    ) -> bool:
        opponent = snapshot.opponent_player or {}
        if str(opponent.get("currentNodeId") or "") != current:
            return False
        if str(opponent.get("state") or "") != "PROCESSING":
            return False
        return self._available_current_horse_resource(snapshot, current) is not None

    def _downstream_resource_free_task_on_endgame_path(
        self,
        context: GameContext,
        snapshot: GameSnapshot,
        *,
        min_score: int,
        extra_current_rounds: int = 0,
    ) -> dict[str, Any] | None:
        current = str(snapshot.self_player.get("currentNodeId") or "")
        if not current:
            return None
        target = context.terminal_node_id if self._effective_verified(snapshot.self_player) else context.gate_node_id
        blocked = self._blocked_nodes(context, snapshot)
        path = context.graph.shortest_path(current, target, blocked=blocked)
        if not path:
            path = context.graph.shortest_path(current, target)
        if len(path) < 2:
            return None

        for task in sorted(snapshot.tasks, key=self._task_sort_key):
            if int(task.get("score") or 0) < min_score:
                continue
            if not self._task_available_for_self(context, task):
                continue
            if self._task_claim_skipped(context, snapshot, task):
                continue
            if self._missing_task_resources(context, snapshot, task):
                continue
            node_id = str(task.get("nodeId") or "")
            if not node_id or node_id == current or node_id not in path[1:]:
                continue
            node_index = path.index(node_id)
            travel_rounds = context.graph.path_movement_rounds(path[: node_index + 1])
            if travel_rounds is None or travel_rounds > DOWNSTREAM_RACE_MAX_TRAVEL_ROUNDS:
                continue
            if not self._can_finish_after_remote_task(
                context,
                snapshot,
                task,
                node_id,
                extra_current_rounds + travel_rounds,
            ):
                continue
            return task
        return None

    @staticmethod
    def _has_opponent_route_pressure(snapshot: GameSnapshot, current: str) -> bool:
        opponent = snapshot.opponent_player or {}
        if opponent.get("delivered"):
            return False
        if str(opponent.get("state") or "") in {"DELIVERED", "RETIRED"}:
            return False
        return current in {
            str(opponent.get("currentNodeId") or ""),
            str(opponent.get("nextNodeId") or ""),
        }

    def _nearest_horse_transfer_task(self, context: GameContext, snapshot: GameSnapshot) -> dict[str, Any] | None:
        current = str(snapshot.self_player.get("currentNodeId") or "")
        if not current:
            return None
        blocked = self._blocked_nodes(context, snapshot)
        best_task: dict[str, Any] | None = None
        best_rounds: int | None = None
        for task in sorted(snapshot.tasks, key=self._task_sort_key):
            if not self._task_available_for_self(context, task):
                continue
            if not self._task_accepts_horse_resource(context, task):
                continue
            node_id = str(task.get("nodeId") or "")
            if not node_id or node_id == current or node_id in blocked:
                continue
            rounds = self._shortest_rounds(context, current, node_id, blocked)
            if rounds is None:
                rounds = self._shortest_rounds(context, current, node_id, set())
            if rounds is None:
                continue
            if best_rounds is None or rounds < best_rounds:
                best_task = task
                best_rounds = rounds
        return best_task

    def _current_available_tasks(self, context: GameContext, snapshot: GameSnapshot) -> list[dict[str, Any]]:
        current = snapshot.self_player.get("currentNodeId")
        if not current:
            return []
        tasks: list[dict[str, Any]] = []
        for task in sorted(snapshot.tasks, key=self._task_sort_key):
            if str(task.get("nodeId")) != str(current):
                continue
            if not self._task_available_for_self(context, task):
                continue
            if self._task_claim_skipped(context, snapshot, task):
                continue
            tasks.append(task)
        return tasks

    def _task_claim_skipped(self, context: GameContext, snapshot: GameSnapshot, task: dict[str, Any]) -> bool:
        task_id = str(task.get("taskId") or "")
        if not task_id or task_id not in self.memory.skipped_task_claims:
            return False

        current = str(snapshot.self_player.get("currentNodeId") or "")
        opponent = snapshot.opponent_player or {}
        opponent_state = str(opponent.get("state") or "IDLE")
        opponent_same_node = str(opponent.get("currentNodeId") or "") == current
        opponent_still_competing = (
            opponent_same_node
            and not opponent.get("delivered")
            and opponent_state not in {"DELIVERED", "RETIRED", "MOVING"}
        )
        if opponent_still_competing:
            if self._should_retry_drawn_high_value_task(context, snapshot, task):
                self.memory.drawn_task_retry_counts[task_id] = self.memory.drawn_task_retry_counts.get(task_id, 0) + 1
                self.memory.skipped_task_claims.discard(task_id)
                self.last_reason = f"retry drawn high-value task {task_id}"
                return False
            self.last_reason = f"skip drawn task {task_id} while opponent remains at {current}"
            return True

        self.memory.skipped_task_claims.discard(task_id)
        self.memory.drawn_task_retry_counts.pop(task_id, None)
        return False

    def _should_retry_drawn_high_value_task(
        self,
        context: GameContext,
        snapshot: GameSnapshot,
        task: dict[str, Any],
    ) -> bool:
        task_id = str(task.get("taskId") or "")
        if not task_id:
            return False
        if self.memory.drawn_task_retry_counts.get(task_id, 0) >= DRAWN_TASK_RETRY_LIMIT:
            return False

        opponent = snapshot.opponent_player or {}
        if str(opponent.get("state") or "IDLE") != "IDLE":
            return False
        if self._ordinary_task_base_score(context, snapshot) < BASE_TASK_RESOURCE_SCORE:
            return False
        if self._opponent_ordinary_task_base_score(context, snapshot) >= BASE_TASK_RESOURCE_SCORE:
            return False
        if int(task.get("score") or 0) < DOWNSTREAM_RACE_MIN_TASK_SCORE:
            return False
        if self._missing_task_resources(context, snapshot, task):
            return False
        if not self._can_finish_after_current_task(context, snapshot, task):
            return False

        current = str(snapshot.self_player.get("currentNodeId") or "")
        task_score = int(task.get("score") or 0)
        for alternate in snapshot.tasks:
            alternate_id = str(alternate.get("taskId") or "")
            if not alternate_id or alternate_id == task_id:
                continue
            if alternate_id in self.memory.skipped_task_claims:
                continue
            if str(alternate.get("nodeId") or "") != current:
                continue
            if not self._task_available_for_self(context, alternate):
                continue
            alternate_score = int(alternate.get("score") or 0)
            if alternate_score <= 0 or alternate_score > LOW_VALUE_ROUTE_TASK_SCORE or alternate_score >= task_score:
                continue
            if self._missing_task_resources(context, snapshot, alternate):
                continue
            return True
        return False

    def _can_finish_after_current_task(
        self,
        context: GameContext,
        snapshot: GameSnapshot,
        task: dict[str, Any],
    ) -> bool:
        current = str(snapshot.self_player.get("currentNodeId") or "")
        if not current:
            return False
        remaining_rounds = context.duration_round - snapshot.round_no
        if remaining_rounds <= 0:
            return False

        task_rounds = max(1, int(task.get("processRound") or 1))
        travel_rounds = self._endgame_travel_rounds(context, snapshot, current)
        if travel_rounds is None:
            return False
        verify_rounds = 0 if self._effective_verified(snapshot.self_player) else self._gate_verify_rounds(context, snapshot)
        required_rounds = (
            task_rounds
            + travel_rounds
            + verify_rounds
            + DELIVERY_SUBMIT_BUFFER_ROUNDS
            + ENDGAME_TASK_SAFETY_BUFFER_ROUNDS
        )
        return remaining_rounds >= required_rounds

    def _can_finish_after_current_task_with_pending_process(
        self,
        context: GameContext,
        snapshot: GameSnapshot,
        task: dict[str, Any],
        process_rounds: int,
    ) -> bool:
        current = str(snapshot.self_player.get("currentNodeId") or "")
        if not current:
            return False
        remaining_rounds = context.duration_round - snapshot.round_no
        if remaining_rounds <= 0:
            return False

        task_rounds = max(1, int(task.get("processRound") or 1))
        travel_rounds = self._endgame_travel_rounds(context, snapshot, current)
        if travel_rounds is None:
            return False
        verify_rounds = 0 if self._effective_verified(snapshot.self_player) else self._gate_verify_rounds(context, snapshot)
        required_rounds = (
            task_rounds
            + max(0, process_rounds)
            + travel_rounds
            + verify_rounds
            + DELIVERY_SUBMIT_BUFFER_ROUNDS
            + ENDGAME_TASK_SAFETY_BUFFER_ROUNDS
        )
        return remaining_rounds >= required_rounds

    def _can_finish_after_remote_task(
        self,
        context: GameContext,
        snapshot: GameSnapshot,
        task: dict[str, Any],
        task_node_id: str,
        travel_to_task_rounds: int,
    ) -> bool:
        remaining_rounds = context.duration_round - snapshot.round_no
        if remaining_rounds <= 0:
            return False

        task_rounds = max(1, int(task.get("processRound") or 1))
        endgame_travel_rounds = self._endgame_travel_rounds(context, snapshot, task_node_id)
        if endgame_travel_rounds is None:
            return False
        verify_rounds = 0 if self._effective_verified(snapshot.self_player) else self._gate_verify_rounds(context, snapshot)
        required_rounds = (
            travel_to_task_rounds
            + self._remote_task_resource_rounds(context, snapshot, task, task_node_id)
            + task_rounds
            + endgame_travel_rounds
            + verify_rounds
            + DELIVERY_SUBMIT_BUFFER_ROUNDS
            + ENDGAME_TASK_SAFETY_BUFFER_ROUNDS
        )
        return remaining_rounds >= required_rounds

    def _remote_task_resource_rounds(
        self,
        context: GameContext,
        snapshot: GameSnapshot,
        task: dict[str, Any],
        task_node_id: str,
    ) -> int:
        missing_resources = self._missing_task_resources(context, snapshot, task)
        if not missing_resources:
            return 0
        node = snapshot.nodes_by_id.get(task_node_id) or {}
        stock = node.get("resourceStock") or {}
        if self._task_accepts_horse_resource(context, task) and any(
            resource_type in HORSE_RESOURCE_TYPES for resource_type in missing_resources
        ):
            if any(int(stock.get(resource_type) or 0) > 0 for resource_type in HORSE_RESOURCE_PRIORITY):
                return 2
            return 0
        claimable = sum(1 for resource_type in missing_resources if int(stock.get(resource_type) or 0) > 0)
        return claimable * 2

    def _endgame_travel_rounds(self, context: GameContext, snapshot: GameSnapshot, current: str) -> int | None:
        blocked = self._blocked_nodes(context, snapshot)
        if self._effective_verified(snapshot.self_player):
            return self._shortest_rounds(context, current, context.terminal_node_id, blocked)

        to_gate = self._shortest_rounds(context, current, context.gate_node_id, blocked)
        gate_to_terminal = self._shortest_rounds(context, context.gate_node_id, context.terminal_node_id, blocked)
        if to_gate is None or gate_to_terminal is None:
            return None
        return to_gate + gate_to_terminal

    def _shortest_rounds(
        self,
        context: GameContext,
        start: str,
        target: str,
        blocked: set[str],
    ) -> int | None:
        rounds = context.graph.shortest_path_movement_rounds(start, target, blocked=blocked)
        if rounds is not None:
            return rounds
        return context.graph.shortest_path_movement_rounds(start, target)

    def _gate_verify_rounds(self, context: GameContext, snapshot: GameSnapshot) -> int:
        gate = snapshot.nodes_by_id.get(context.gate_node_id) or {}
        return max(1, int(gate.get("processRound") or 6))

    def _claim_required_current_resource(
        self,
        context: GameContext,
        snapshot: GameSnapshot,
        current: Any,
        missing_resources: list[str],
        task: dict[str, Any],
    ) -> dict[str, Any] | None:
        node = snapshot.nodes_by_id.get(str(current), {})
        stock = node.get("resourceStock") or {}
        if self._task_accepts_horse_resource(context, task) and any(
            resource_type in HORSE_RESOURCE_TYPES for resource_type in missing_resources
        ):
            resource_type = self._available_current_horse_resource(snapshot, current)
            if resource_type is not None:
                self.last_reason = (
                    f"claim required horse resource {resource_type} for task {task.get('taskId')} at {current}"
                )
                return {"action": "CLAIM_RESOURCE", "targetNodeId": str(current), "resourceType": resource_type}

        for resource_type in self._sort_resource_types(missing_resources):
            if int(stock.get(resource_type) or 0) <= 0:
                continue
            if self._resource_claim_skipped(current, resource_type):
                continue
            if self._opponent_processing_resource(snapshot, current, resource_type):
                continue
            self.last_reason = f"claim required resource {resource_type} for task {task.get('taskId')} at {current}"
            return {"action": "CLAIM_RESOURCE", "targetNodeId": str(current), "resourceType": resource_type}
        return None

    def _missing_task_resources(
        self,
        context: GameContext,
        snapshot: GameSnapshot,
        task: dict[str, Any],
    ) -> list[str]:
        required = self._task_required_resources(context, task)
        if not required:
            return []
        resources = snapshot.self_player.get("resources") or {}
        missing: list[str] = []
        accepts_horse = self._task_accepts_horse_resource(context, task)
        for resource_type in required:
            if accepts_horse and resource_type in HORSE_RESOURCE_TYPES:
                if self._has_any_resource(snapshot.self_player, HORSE_RESOURCE_TYPES):
                    continue
                if not any(existing in HORSE_RESOURCE_TYPES for existing in missing):
                    missing.append(resource_type)
                continue
            if int(resources.get(resource_type) or 0) <= 0:
                missing.append(resource_type)
        return missing

    def _task_required_resources(self, context: GameContext, task: dict[str, Any]) -> list[str]:
        direct = self._coerce_resource_types(task.get("requiredResourceTypes"))
        if direct:
            return direct
        template_id = task.get("taskTemplateId")
        if not template_id:
            return []
        template = self._task_template(context, str(template_id))
        if template is None:
            return []
        return self._coerce_resource_types(template.get("requiredResourceTypes"))

    def _task_template(self, context: GameContext, template_id: str) -> dict[str, Any] | None:
        raw_start = context.raw_start or {}
        template_groups = [raw_start.get("taskTemplates") or []]
        map_data = raw_start.get("map") or {}
        template_groups.append(map_data.get("taskTemplates") or [])
        for templates in template_groups:
            for template in templates:
                if str(template.get("taskTemplateId") or "") == template_id:
                    return template
        return None

    def _task_accepts_horse_resource(self, context: GameContext, task: dict[str, Any]) -> bool:
        template_id = str(task.get("taskTemplateId") or "")
        process_type = str(task.get("processType") or "")
        if template_id in HORSE_TRANSFER_TEMPLATE_IDS or process_type in HORSE_TRANSFER_PROCESS_TYPES:
            return True
        if not template_id:
            return False
        template = self._task_template(context, template_id)
        if template is None:
            return False
        return (
            str(template.get("taskTemplateId") or "") in HORSE_TRANSFER_TEMPLATE_IDS
            or str(template.get("processType") or "") in HORSE_TRANSFER_PROCESS_TYPES
        )

    @staticmethod
    def _coerce_resource_types(value: Any) -> list[str]:
        if not value:
            return []
        if isinstance(value, str):
            return [value]
        if isinstance(value, (list, tuple, set)):
            return [str(item) for item in value if item]
        return []

    @classmethod
    def _sort_resource_types(cls, resource_types: list[str]) -> list[str]:
        priority = {resource_type: index for index, resource_type in enumerate(RESOURCE_PRIORITY)}
        return sorted(resource_types, key=lambda item: (priority.get(item, len(priority)), item))

    def _claim_current_resource(self, context: GameContext, snapshot: GameSnapshot) -> dict[str, Any] | None:
        current = snapshot.self_player.get("currentNodeId")
        node = snapshot.nodes_by_id.get(str(current), {})
        stock = node.get("resourceStock") or {}
        skipped: list[str] = []
        for resource_type in RESOURCE_PRIORITY:
            if int(stock.get(resource_type) or 0) > 0:
                if resource_type in HORSE_RESOURCE_TYPES and self._should_defer_current_horse_resource_for_downstream_race(
                    context,
                    snapshot,
                ):
                    skipped.append(f"{resource_type}:downstream-task-race")
                    continue
                if self._low_yield_resource_after_base_score(context, snapshot, resource_type):
                    skipped.append(f"{resource_type}:base-task-score")
                    continue
                if self._low_yield_resource_blocks_task_race(context, snapshot, resource_type):
                    skipped.append(f"{resource_type}:task-race")
                    continue
                if self._resource_claim_skipped(current, resource_type):
                    skipped.append(f"{resource_type}:drawn-contest")
                    continue
                if self._opponent_processing_resource(snapshot, current, resource_type):
                    skipped.append(f"{resource_type}:opponent-processing")
                    continue
                if self._would_start_low_value_resource_contest(snapshot, current, resource_type, stock):
                    skipped.append(f"{resource_type}:low-value-contest")
                    continue
                self.last_reason = f"claim resource {resource_type} at {current}"
                return {"action": "CLAIM_RESOURCE", "targetNodeId": str(current), "resourceType": resource_type}
        if skipped:
            self.last_reason = "skip resource " + ",".join(skipped)
        return None

    def _should_defer_current_horse_resource_for_downstream_race(
        self,
        context: GameContext,
        snapshot: GameSnapshot,
    ) -> bool:
        for task in self._current_available_tasks(context, snapshot):
            if self._should_defer_horse_task_for_downstream_race(context, snapshot, task):
                return True
        return False

    def _low_yield_resource_after_base_score(
        self,
        context: GameContext,
        snapshot: GameSnapshot,
        resource_type: str,
    ) -> bool:
        if resource_type not in LOW_YIELD_OPTIONAL_RESOURCES:
            return False
        return self._ordinary_task_base_score(context, snapshot) >= BASE_TASK_RESOURCE_SCORE

    def _low_yield_resource_blocks_task_race(
        self,
        context: GameContext,
        snapshot: GameSnapshot,
        resource_type: str,
    ) -> bool:
        if resource_type not in LOW_YIELD_OPTIONAL_RESOURCES:
            return False
        if self._ordinary_task_base_score(context, snapshot) >= BASE_TASK_RESOURCE_SCORE:
            return False
        current = str(snapshot.self_player.get("currentNodeId") or "")
        if not current:
            return False

        blocked = self._blocked_nodes(context, snapshot)
        for task in sorted(snapshot.tasks, key=self._task_sort_key):
            if not self._task_available_for_self(context, task):
                continue
            if self._task_claim_skipped(context, snapshot, task):
                continue
            if not self._task_route_viable(context, snapshot, task):
                continue
            node_id = str(task.get("nodeId") or "")
            if not node_id or node_id == current or node_id in blocked:
                continue
            rounds = self._shortest_rounds(context, current, node_id, blocked)
            if rounds is None:
                rounds = self._shortest_rounds(context, current, node_id, set())
            if rounds is None:
                continue
            if self._can_finish_after_remote_task(context, snapshot, task, node_id, rounds):
                return True
        return False

    def _available_current_horse_resource(self, snapshot: GameSnapshot, current: Any) -> str | None:
        node = snapshot.nodes_by_id.get(str(current), {})
        stock = node.get("resourceStock") or {}
        for resource_type in HORSE_RESOURCE_PRIORITY:
            if int(stock.get(resource_type) or 0) <= 0:
                continue
            if self._resource_claim_skipped(current, resource_type):
                continue
            if self._opponent_processing_resource(snapshot, current, resource_type):
                continue
            return resource_type
        return None

    def _resource_claim_skipped(self, current: Any, resource_type: str) -> bool:
        if not current or not resource_type:
            return False
        key = self.memory.resource_claim_key(current, resource_type)
        return key in self.memory.skipped_resource_claims

    @staticmethod
    def _has_any_resource(player: dict[str, Any], resource_types: set[str]) -> bool:
        resources = player.get("resources") or {}
        return any(int(resources.get(resource_type) or 0) > 0 for resource_type in resource_types)

    def _opponent_processing_resource(self, snapshot: GameSnapshot, current: Any, resource_type: str) -> bool:
        opponent = snapshot.opponent_player or {}
        if str(opponent.get("currentNodeId") or "") != str(current):
            return False
        if str(opponent.get("state") or "") != "PROCESSING":
            return False
        process = opponent.get("currentProcess") or {}
        if str(process.get("action") or "") != "CLAIM_RESOURCE":
            return False
        return str(process.get("resourceType") or "") == resource_type

    def _would_start_low_value_resource_contest(
        self,
        snapshot: GameSnapshot,
        current: Any,
        resource_type: str,
        stock: dict[str, Any],
    ) -> bool:
        if resource_type not in LOW_VALUE_CONTEST_RESOURCES:
            return False
        if int(stock.get(resource_type) or 0) > 1:
            return False
        opponent = snapshot.opponent_player or {}
        if str(opponent.get("currentNodeId") or "") != str(current):
            return False
        if opponent.get("delivered") or str(opponent.get("state") or "") in {"DELIVERED", "RETIRED"}:
            return False
        if str(opponent.get("state") or "IDLE") != "IDLE":
            return False
        return True

    def _would_start_idle_resource_contest(
        self,
        snapshot: GameSnapshot,
        current: Any,
        resource_type: str,
    ) -> bool:
        if not current or not resource_type:
            return False
        node = snapshot.nodes_by_id.get(str(current), {})
        stock = node.get("resourceStock") or {}
        if int(stock.get(resource_type) or 0) > 1:
            return False
        opponent = snapshot.opponent_player or {}
        if str(opponent.get("currentNodeId") or "") != str(current):
            return False
        if opponent.get("delivered") or str(opponent.get("state") or "") in {"DELIVERED", "RETIRED", "MOVING"}:
            return False
        return str(opponent.get("state") or "IDLE") == "IDLE"

    def _choose_destination(self, context: GameContext, snapshot: GameSnapshot) -> str | None:
        player = snapshot.self_player
        task_score = int(player.get("taskScore") or 0)
        if self._should_go_endgame(context, snapshot):
            return context.terminal_node_id if self._effective_verified(player) else context.gate_node_id
        if task_score < 90:
            target = self._nearest_task_node(context, snapshot)
            if target:
                self.last_reason = f"go to task node {target}"
                return target
        target = context.terminal_node_id if self._effective_verified(player) else context.gate_node_id
        self.last_reason = f"default endgame target {target}"
        return target

    def _nearest_task_node(self, context: GameContext, snapshot: GameSnapshot) -> str | None:
        current = snapshot.self_player.get("currentNodeId")
        blocked = self._blocked_nodes(context, snapshot)
        best_node_id: str | None = None
        best_rounds: int | None = None
        for task in sorted(snapshot.tasks, key=self._task_sort_key):
            if not self._task_available_for_self(context, task):
                continue
            if self._task_claim_skipped(context, snapshot, task):
                continue
            if not self._task_route_viable(context, snapshot, task):
                continue
            node_id = str(task.get("nodeId") or "")
            if not node_id or node_id in blocked:
                continue
            if node_id == str(current) and self._should_defer_horse_task_for_downstream_race(context, snapshot, task):
                continue
            path = context.graph.shortest_path(str(current), node_id, blocked=blocked)
            if not path:
                continue
            rounds = context.graph.path_movement_rounds(path)
            if rounds is None:
                continue
            if not self._can_finish_after_remote_task(context, snapshot, task, node_id, rounds):
                continue
            if best_rounds is None or rounds < best_rounds:
                best_node_id = node_id
                best_rounds = rounds
        return best_node_id

    def _task_route_viable(self, context: GameContext, snapshot: GameSnapshot, task: dict[str, Any]) -> bool:
        missing_resources = self._missing_task_resources(context, snapshot, task)
        if not missing_resources:
            return True
        node_id = str(task.get("nodeId") or "")
        node = snapshot.nodes_by_id.get(node_id)
        if node is None:
            return True
        stock = node.get("resourceStock") or {}
        if self._task_accepts_horse_resource(context, task) and any(
            resource_type in HORSE_RESOURCE_TYPES for resource_type in missing_resources
        ):
            return any(
                int(stock.get(resource_type) or 0) > 0
                and not self._resource_claim_skipped(node_id, resource_type)
                for resource_type in HORSE_RESOURCE_PRIORITY
            )
        return any(
            int(stock.get(resource_type) or 0) > 0
            and not self._resource_claim_skipped(node_id, resource_type)
            for resource_type in missing_resources
        )

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
        blocker_action = self._blocked_adjacent_action(context, snapshot, str(current), next_node)
        if blocker_action is not None:
            return blocker_action
        blocker = self._entry_blocker(context, snapshot, next_node, origin=current)
        if blocker:
            self.last_reason = f"blocked from {current} to {next_node}: {blocker}"
            return None
        self.last_reason = f"move from {current} to {next_node} toward {target}"
        return {"action": "MOVE", "targetNodeId": next_node}

    def _blocked_nodes(self, context: GameContext, snapshot: GameSnapshot) -> set[str]:
        blocked = self._hard_blocked_nodes(context, snapshot)
        blocked.update(self._guard_threat_nodes(context, snapshot))
        blocked.discard(context.terminal_node_id)
        return blocked

    def _hard_blocked_nodes(self, context: GameContext, snapshot: GameSnapshot) -> set[str]:
        blocked: set[str] = set()
        for node_id, node in snapshot.nodes_by_id.items():
            if node.get("hasObstacle"):
                blocked.add(node_id)
                continue
            guard = node.get("guard") or {}
            if guard.get("active") and guard.get("ownerTeamId") != context.team_id:
                blocked.add(node_id)
        blocked.update(self.memory.blocked_move_targets)
        blocked.discard(context.terminal_node_id)
        return blocked

    def _guard_threat_nodes(self, context: GameContext, snapshot: GameSnapshot) -> set[str]:
        player = snapshot.self_player
        current = str(player.get("currentNodeId") or "")
        opponent = snapshot.opponent_player or {}
        if not current or opponent.get("delivered") or str(opponent.get("state") or "") in {"DELIVERED", "RETIRED"}:
            return set()
        hard_blocked = self._hard_blocked_nodes(context, snapshot)
        threats: set[str] = set()
        for node_id, node in snapshot.nodes_by_id.items():
            node_key = str(node_id)
            if node_key in hard_blocked:
                continue
            if not self._guardable_node(context, node_key, node):
                continue
            ready_rounds = self._opponent_guard_ready_rounds(opponent, node_key)
            if ready_rounds is None:
                continue
            arrival_rounds = context.graph.shortest_path_movement_rounds(current, node_key, blocked=hard_blocked)
            if arrival_rounds is None:
                continue
            if ready_rounds <= arrival_rounds:
                threats.add(node_key)
        return threats

    @staticmethod
    def _guardable_node(context: GameContext, node_id: str, node: dict[str, Any]) -> bool:
        if node_id == context.terminal_node_id or node.get("terminal") is True or node.get("safeZone") is True:
            return False
        guard = node.get("guard") or {}
        return not bool(guard.get("active") and int(guard.get("defense") or 0) > 0)

    def _opponent_guard_ready_rounds(self, opponent: dict[str, Any], node_id: str) -> int | None:
        process = opponent.get("currentProcess") or {}
        process_action = str(process.get("action") or process.get("type") or "").upper()
        process_target = str(process.get("targetNodeId") or opponent.get("currentNodeId") or "")
        if process_action == "SET_GUARD" and process_target == node_id:
            return max(1, self._remaining_process_rounds(process) + 1)

        state = str(opponent.get("state") or "IDLE")
        current = str(opponent.get("currentNodeId") or "")
        next_node = str(opponent.get("nextNodeId") or "")
        if current == node_id and state in {"IDLE", "WAITING"} and not next_node:
            return GUARD_ACTIVE_AFTER_START_ROUNDS
        if next_node == node_id and state in {"MOVING", "WAITING"}:
            return self._remaining_move_rounds(opponent) + GUARD_ACTIVE_AFTER_START_ROUNDS
        return None

    @staticmethod
    def _remaining_process_rounds(process: dict[str, Any]) -> int:
        for key in ("remainRound", "remainingRound"):
            try:
                return max(0, int(process.get(key) or 0))
            except (TypeError, ValueError):
                continue
        return 0

    @staticmethod
    def _remaining_move_rounds(player: dict[str, Any]) -> int:
        try:
            total = int(player.get("edgeTotalMs") or 0)
            progress = int(player.get("edgeProgressMs") or 0)
        except (TypeError, ValueError):
            total = 0
            progress = 0
        if total > 0:
            return max(1, ceil(max(0, total - progress) / 1000))
        for key in ("moveRemainRound", "remainingRound", "remainRound"):
            try:
                value = int(player.get(key) or 0)
            except (TypeError, ValueError):
                continue
            if value > 0:
                return value
        return 1

    def _blocked_adjacent_action(
        self,
        context: GameContext,
        snapshot: GameSnapshot,
        current: str,
        target: str,
    ) -> dict[str, Any] | None:
        if self._special_terminal_return(context, current, target):
            return None
        node = snapshot.nodes_by_id.get(str(target), {})
        if self._enemy_guard_active(context, node):
            action = self._break_guard_action(context, snapshot, target, node.get("guard") or {})
            if action is not None:
                return action
            if target not in self.memory.forced_pass_blocked_nodes:
                self.last_reason = f"force pass enemy guard at {target}"
                return {"action": "FORCED_PASS", "targetNodeId": target}
            self.last_reason = f"avoid repeated forced pass at {target}"
            return None
        if node.get("hasObstacle"):
            if self._should_force_pass_obstacle(context, snapshot, target):
                self.last_reason = f"force pass obstacle at {target}"
                return {"action": "FORCED_PASS", "targetNodeId": target}
            if int(snapshot.self_player.get("goodFruit") or 0) > MIN_GOOD_FRUIT_AFTER_BREAK:
                self.last_reason = f"clear obstacle at {target}"
                return {"action": "CLEAR", "targetNodeId": target}
            if target not in self.memory.forced_pass_blocked_nodes:
                self.last_reason = f"force pass low-resource obstacle at {target}"
                return {"action": "FORCED_PASS", "targetNodeId": target}
        return None

    def _break_guard_action(
        self,
        context: GameContext,
        snapshot: GameSnapshot,
        target: str,
        guard: dict[str, Any],
    ) -> dict[str, Any] | None:
        defense = int(guard.get("defense") or 0)
        if defense <= 0:
            return None
        player = snapshot.self_player
        max_bad = min(2, int(player.get("badFruit") or 0))
        max_good = min(2, max(0, int(player.get("goodFruit") or 0) - MIN_GOOD_FRUIT_AFTER_BREAK))
        can_bind_break_order = self._can_bind_break_order_to_break_guard(snapshot)
        best: tuple[int, int, int] | None = None
        for use_break_order in (False, True):
            if use_break_order and not can_bind_break_order:
                continue
            rush_bonus = 3 if use_break_order else 0
            for bad in range(max_bad + 1):
                for good in range(max_good + 1):
                    attack = bad * 3 + good * 2 + rush_bonus
                    if attack <= 0 or attack < defense:
                        continue
                    candidate = (1 if use_break_order else 0, good, bad)
                    if best is None or candidate < best:
                        best = candidate
        if best is None:
            return None
        _, good, bad = best
        use_break_order = bool(best[0])
        action: dict[str, Any] = {"action": "BREAK_GUARD", "targetNodeId": target}
        if good:
            action["goodFruit"] = good
        if bad:
            action["badFruit"] = bad
        if use_break_order:
            action["rushTactic"] = "BREAK_ORDER"
        self.last_reason = f"break enemy guard at {target}"
        return action

    @staticmethod
    def _can_bind_break_order_to_break_guard(snapshot: GameSnapshot) -> bool:
        player = snapshot.self_player
        if snapshot.phase != "RUSH" or int(player.get("rushTacticUsedCount") or 0) > 0:
            return False
        return int(player.get("badFruit") or 0) >= 2 or int(player.get("goodFruit") or 0) > MIN_GOOD_FRUIT_AFTER_BREAK

    def _should_force_pass_obstacle(self, context: GameContext, snapshot: GameSnapshot, target: str) -> bool:
        if target == context.gate_node_id and snapshot.phase == "RUSH":
            return True
        if self._should_go_endgame(context, snapshot):
            return True
        return int(snapshot.self_player.get("goodFruit") or 0) <= MIN_GOOD_FRUIT_AFTER_BREAK

    def _entry_blocker(
        self,
        context: GameContext,
        snapshot: GameSnapshot,
        target: str,
        *,
        origin: Any = None,
    ) -> str | None:
        origin_key = str(origin or "")
        if self._special_terminal_return(context, origin_key, target):
            return None
        node = snapshot.nodes_by_id.get(str(target), {})
        if self._enemy_guard_active(context, node):
            return "enemy guard"
        if node.get("hasObstacle"):
            return "obstacle"
        return None

    @staticmethod
    def _enemy_guard_active(context: GameContext, node: dict[str, Any]) -> bool:
        guard = node.get("guard") or {}
        return bool(guard.get("active") and guard.get("ownerTeamId") != context.team_id and int(guard.get("defense") or 0) > 0)

    @staticmethod
    def _special_terminal_return(context: GameContext, origin: str, target: str) -> bool:
        return str(origin) == context.terminal_node_id and str(target) == context.gate_node_id

    def _should_go_endgame(self, context: GameContext, snapshot: GameSnapshot) -> bool:
        player = snapshot.self_player
        if snapshot.phase == "RUSH":
            return True
        if snapshot.round_no >= min(430, context.duration_round - 120):
            return True
        if float(player.get("freshness") or 0) <= 20:
            return True
        if int(player.get("goodFruit") or 0) <= 5:
            return True
        return False

    def _task_available_for_self(self, context: GameContext, task: dict[str, Any]) -> bool:
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
        return True

    @staticmethod
    def _task_sort_key(task: dict[str, Any]) -> tuple[int, int, str]:
        return (-int(task.get("score") or 0), int(task.get("expireRound") or 10**9), str(task.get("taskId") or ""))
