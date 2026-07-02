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

        process_action = self._process_current_node(context, snapshot)
        if process_action is not None:
            return process_action

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
        for resource_type in RESOURCE_PRIORITY:
            if int(stock.get(resource_type) or 0) > 0:
                self.last_reason = f"claim resource {resource_type} at {current}"
                return {"action": "CLAIM_RESOURCE", "targetNodeId": str(current), "resourceType": resource_type}
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
