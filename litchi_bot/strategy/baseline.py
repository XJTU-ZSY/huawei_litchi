from __future__ import annotations

from typing import Any

from litchi_bot.core.game_state import StaticGame, TurnState
from litchi_bot.core.models import NodeState, normalize_player_id

from .base import BaseStrategy


class BaselineStrategy(BaseStrategy):
    """Conservative delivery-first strategy.

    This strategy deliberately ignores tasks, resources, contests, and obstacles for now.
    Its job is to keep the bot moving toward verification and delivery without sending
    obviously illegal actions.
    """

    def __init__(self, player_id: int | str) -> None:
        self.player_id = normalize_player_id(player_id)
        self.static_game: StaticGame | None = None
        self._last_current_node_id: str | None = None
        self._processed_node_for_current_visit: str | None = None

    def on_start(self, start_data: dict[str, Any]) -> None:
        self.static_game = StaticGame.from_start(start_data, self.player_id)
        self._last_current_node_id = None
        self._processed_node_for_current_visit = None

    def decide(self, inquire_data: dict[str, Any]) -> list[dict[str, Any]]:
        if self.static_game is None:
            return []

        turn = TurnState.from_inquire(inquire_data, self.static_game)
        me = turn.me
        if me is None:
            return []

        if me.current_node_id != self._last_current_node_id:
            self._processed_node_for_current_visit = None
            self._last_current_node_id = me.current_node_id

        self._record_process_completion(turn)

        if me.delivered or me.retired or me.is_blocked:
            return []

        if me.state == "MOVING":
            return []

        if me.state == "WAITING" and me.next_node_id:
            return [{"action": "MOVE", "targetNodeId": me.next_node_id}]

        if me.current_node_id is None:
            return []

        if me.current_node_id in self.static_game.terminal_node_ids:
            return self._terminal_action(turn)

        if me.current_node_id == self.static_game.gate_node_id:
            return self._gate_action(turn)

        current_node_state = self._current_node_state(turn)
        if self._should_process_current_node(current_node_state):
            return [{"action": "PROCESS", "targetNodeId": me.current_node_id}]

        target_nodes = [self.static_game.gate_node_id] if not me.verified else list(self.static_game.terminal_node_ids)
        next_hop = self.static_game.graph.next_hop(me.current_node_id, target_nodes)
        if next_hop is None:
            return []

        return [{"action": "MOVE", "targetNodeId": next_hop}]

    def _terminal_action(self, turn: TurnState) -> list[dict[str, Any]]:
        me = turn.me
        if me is None:
            return []
        if me.can_deliver:
            return [{"action": "DELIVER"}]
        if not me.verified:
            next_hop = self.static_game.graph.next_hop(me.current_node_id or "", [self.static_game.gate_node_id])
            if next_hop is not None:
                return [{"action": "MOVE", "targetNodeId": next_hop}]
        return []

    def _gate_action(self, turn: TurnState) -> list[dict[str, Any]]:
        me = turn.me
        if me is None:
            return []
        if not me.verified:
            if turn.phase == "RUSH":
                return [{"action": "VERIFY_GATE", "targetNodeId": self.static_game.gate_node_id}]
            return []

        next_hop = self.static_game.graph.next_hop(me.current_node_id or "", self.static_game.terminal_node_ids)
        if next_hop is None:
            return []
        return [{"action": "MOVE", "targetNodeId": next_hop}]

    def _current_node_state(self, turn: TurnState) -> NodeState | None:
        me = turn.me
        if me is None:
            return None
        node_state = turn.node_state(me.current_node_id)
        if node_state is not None:
            return node_state

        process_node = self.static_game.process_nodes.get(me.current_node_id or "")
        if process_node is None:
            return None
        return NodeState(
            node_id=process_node.node_id,
            process_type=process_node.process_type,
            process_round=process_node.process_round,
        )

    def _should_process_current_node(self, node_state: NodeState | None) -> bool:
        if node_state is None or not node_state.requires_process:
            return False
        return self._processed_node_for_current_visit != node_state.node_id

    def _record_process_completion(self, turn: TurnState) -> None:
        me = turn.me
        if me is None:
            return

        for event in turn.raw_events:
            if event.get("type") != "PROCESS_COMPLETE":
                continue
            payload = event.get("payload")
            if not isinstance(payload, dict):
                continue
            if not self._payload_matches_me(payload, me.team_id):
                continue
            node_id = payload.get("targetNodeId") or payload.get("nodeId")
            if node_id and str(node_id) == me.current_node_id:
                self._processed_node_for_current_visit = str(node_id)

    def _payload_matches_me(self, payload: dict[str, Any], team_id: str | None) -> bool:
        payload_player_id = payload.get("playerId")
        if payload_player_id is not None:
            return normalize_player_id(payload_player_id) == self.player_id
        payload_team_id = payload.get("teamId")
        if payload_team_id is not None and team_id is not None:
            return str(payload_team_id) == team_id
        return False
