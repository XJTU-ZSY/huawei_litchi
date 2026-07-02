from __future__ import annotations

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

FIXED_PROCESS_BUSY_STATES = {"PROCESSING", "VERIFYING", "RESTING", "CONTESTING"}
IDLE_PROCESS_YIELD_LIMIT = 1
ICE_BOX_USE_FRESHNESS_LIMIT = 90.0


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

        if state in {"MOVING", "WAITING"}:
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
            self.last_reason = "rush gate verification"
            return {"action": "VERIFY_GATE"}

        if self._should_yield_fixed_process(context, snapshot):
            return None

        process_action = self._process_current_node(context, snapshot)
        if process_action is not None:
            return process_action

        ice_box_action = self._use_ice_box_if_beneficial(context, snapshot)
        if ice_box_action is not None:
            return ice_box_action

        if self._should_go_endgame(context, snapshot):
            target = context.terminal_node_id if player.get("verified") else context.gate_node_id
            self.last_reason = f"endgame lock target {target}"
            return self._move_toward(context, snapshot, target)

        task_action = self._claim_current_task(context, snapshot)
        if task_action is not None:
            return task_action

        resource_action = self._claim_current_resource(snapshot)
        if resource_action is not None:
            return resource_action

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
        if not self._loses_process_tie(context.player_id, opponent.get("playerId")):
            self._clear_process_yield(str(current))
            return False

        current_key = str(current)
        if opponent_state == "IDLE":
            yielded = self.memory.process_idle_yield_counts.get(current_key, 0)
            if yielded < IDLE_PROCESS_YIELD_LIMIT:
                self.memory.process_idle_yield_counts[current_key] = yielded + 1
                self.last_reason = f"yield process node {current} to opponent {opponent.get('playerId')}"
                return True
            return False

        if opponent_state in FIXED_PROCESS_BUSY_STATES:
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
            if not self._task_available_for_self(context, task):
                continue
            if str(task.get("nodeId")) == str(current):
                self.last_reason = f"claim current task {task.get('taskId')}"
                return {"action": "CLAIM_TASK", "taskId": task["taskId"]}
        return None

    def _claim_current_resource(self, snapshot: GameSnapshot) -> dict[str, Any] | None:
        current = snapshot.self_player.get("currentNodeId")
        node = snapshot.nodes_by_id.get(str(current), {})
        stock = node.get("resourceStock") or {}
        contested = self._opponent_claiming_resources_at_current(snapshot, current)
        for resource_type in RESOURCE_PRIORITY:
            if int(stock.get(resource_type) or 0) > 0:
                if resource_type in contested:
                    continue
                self.last_reason = f"claim resource {resource_type} at {current}"
                return {"action": "CLAIM_RESOURCE", "targetNodeId": str(current), "resourceType": resource_type}
        if contested:
            self.last_reason = f"skip contested resources at {current}: {','.join(sorted(contested))}"
        return None

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
        if task_score < 90:
            target = self._nearest_task_node(context, snapshot)
            if target:
                self.last_reason = f"go to task node {target}"
                return target
        target = context.terminal_node_id if player.get("verified") else context.gate_node_id
        self.last_reason = f"default endgame target {target}"
        return target

    def _nearest_task_node(self, context: GameContext, snapshot: GameSnapshot) -> str | None:
        current = snapshot.self_player.get("currentNodeId")
        blocked = self._blocked_nodes(context, snapshot)
        best_path: list[str] = []
        for task in sorted(snapshot.tasks, key=self._task_sort_key):
            if not self._task_available_for_self(context, task):
                continue
            node_id = str(task.get("nodeId") or "")
            if not node_id or node_id in blocked:
                continue
            path = context.graph.shortest_path(str(current), node_id, blocked=blocked)
            if path and (not best_path or len(path) < len(best_path)):
                best_path = path
        return best_path[-1] if best_path else None

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
        self.last_reason = f"move from {current} to {next_node} toward {target}"
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
