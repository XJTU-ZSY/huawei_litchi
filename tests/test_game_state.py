from __future__ import annotations

import unittest

from litchi_bot.core.game_state import StaticGame, TurnState
from tests.fixtures import inquire_data, player_state, start_message_data


class GameStateTests(unittest.TestCase):
    def test_static_game_parses_roles_edges_process_nodes_and_team(self) -> None:
        static_game = StaticGame.from_start(start_message_data(), "1001")

        self.assertEqual(static_game.team_id, "RED")
        self.assertEqual(static_game.opponent_team_id, "BLUE")
        self.assertEqual(static_game.start_node_id, "S01")
        self.assertEqual(static_game.gate_node_id, "S14")
        self.assertEqual(static_game.terminal_node_ids, ("S15",))
        self.assertIn("S02", static_game.process_nodes)
        self.assertEqual(static_game.graph.next_hop("S01", ["S15"]), "S02")

    def test_turn_state_parses_own_player_and_nodes(self) -> None:
        static_game = StaticGame.from_start(start_message_data(), 1001)
        turn = TurnState.from_inquire(inquire_data(player=player_state(node_id="S02")), static_game)

        self.assertIsNotNone(turn.me)
        self.assertEqual(turn.me.current_node_id, "S02")
        self.assertEqual(turn.node_state("S02").process_type, "TRANSFER")


if __name__ == "__main__":
    unittest.main()
