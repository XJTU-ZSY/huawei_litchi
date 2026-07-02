from __future__ import annotations

import unittest

from litchi_bot.strategy.baseline import BaselineStrategy
from tests.fixtures import inquire_data, player_state, start_message_data


class BaselineStrategyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.strategy = BaselineStrategy("1001")
        self.strategy.on_start(start_message_data())

    def test_moves_toward_gate_from_normal_node(self) -> None:
        actions = self.strategy.decide(inquire_data(player=player_state(node_id="S01")))

        self.assertEqual(actions, [{"action": "MOVE", "targetNodeId": "S02"}])

    def test_processes_fixed_process_node_before_leaving(self) -> None:
        actions = self.strategy.decide(inquire_data(player=player_state(node_id="S02")))

        self.assertEqual(actions, [{"action": "PROCESS", "targetNodeId": "S02"}])

    def test_moves_after_process_complete_for_current_visit(self) -> None:
        actions = self.strategy.decide(
            inquire_data(
                player=player_state(node_id="S02"),
                events=[
                    {
                        "type": "PROCESS_COMPLETE",
                        "payload": {"playerId": 1001, "targetNodeId": "S02"},
                    }
                ],
            )
        )

        self.assertEqual(actions, [{"action": "MOVE", "targetNodeId": "S14"}])

    def test_resets_process_completion_after_reentering_node(self) -> None:
        self.strategy.decide(
            inquire_data(
                player=player_state(node_id="S02"),
                events=[
                    {
                        "type": "PROCESS_COMPLETE",
                        "payload": {"playerId": 1001, "targetNodeId": "S02"},
                    }
                ],
            )
        )
        self.strategy.decide(inquire_data(player=player_state(node_id="S14"), phase="NORMAL"))

        actions = self.strategy.decide(inquire_data(player=player_state(node_id="S02")))

        self.assertEqual(actions, [{"action": "PROCESS", "targetNodeId": "S02"}])

    def test_waits_at_gate_before_rush_if_not_verified(self) -> None:
        actions = self.strategy.decide(inquire_data(player=player_state(node_id="S14"), phase="NORMAL"))

        self.assertEqual(actions, [])

    def test_verifies_gate_in_rush_phase(self) -> None:
        actions = self.strategy.decide(inquire_data(player=player_state(node_id="S14"), phase="RUSH"))

        self.assertEqual(actions, [{"action": "VERIFY_GATE", "targetNodeId": "S14"}])

    def test_moves_to_terminal_after_verification(self) -> None:
        actions = self.strategy.decide(inquire_data(player=player_state(node_id="S14", verified=True), phase="RUSH"))

        self.assertEqual(actions, [{"action": "MOVE", "targetNodeId": "S15"}])

    def test_delivers_when_terminal_conditions_are_met(self) -> None:
        actions = self.strategy.decide(inquire_data(player=player_state(node_id="S15", verified=True), phase="RUSH"))

        self.assertEqual(actions, [{"action": "DELIVER"}])

    def test_returns_empty_after_delivery(self) -> None:
        actions = self.strategy.decide(
            inquire_data(player=player_state(node_id="S15", verified=True, delivered=True), phase="RUSH")
        )

        self.assertEqual(actions, [])

    def test_returns_empty_while_processing(self) -> None:
        actions = self.strategy.decide(
            inquire_data(
                player=player_state(
                    node_id="S02",
                    state="PROCESSING",
                    current_process={"action": "PROCESS", "targetNodeId": "S02"},
                )
            )
        )

        self.assertEqual(actions, [])

    def test_moving_state_does_not_send_active_wait(self) -> None:
        actions = self.strategy.decide(
            inquire_data(player=player_state(node_id="S01", state="MOVING", next_node_id="S02"))
        )

        self.assertEqual(actions, [])


if __name__ == "__main__":
    unittest.main()
