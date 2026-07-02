from __future__ import annotations

import unittest

from litchi_bot.core.graph import MapGraph


class GraphTests(unittest.TestCase):
    def test_next_hop_uses_lowest_distance_path(self) -> None:
        graph = MapGraph.from_raw_edges(
            [
                {"edgeId": "E1", "fromNodeId": "S01", "toNodeId": "S02", "distance": 3, "bidirectional": True},
                {"edgeId": "E2", "fromNodeId": "S02", "toNodeId": "S14", "distance": 3, "bidirectional": True},
                {"edgeId": "E3", "fromNodeId": "S01", "toNodeId": "S14", "distance": 10, "bidirectional": True},
            ]
        )

        self.assertEqual(graph.shortest_path("S01", ["S14"]), ["S01", "S02", "S14"])
        self.assertEqual(graph.next_hop("S01", ["S14"]), "S02")

    def test_directional_edges_do_not_allow_reverse_move(self) -> None:
        graph = MapGraph.from_raw_edges(
            [
                {"edgeId": "E1", "fromNodeId": "A", "toNodeId": "B", "distance": 1, "bidirectional": False},
            ]
        )

        self.assertEqual(graph.next_hop("A", ["B"]), "B")
        self.assertIsNone(graph.next_hop("B", ["A"]))


if __name__ == "__main__":
    unittest.main()
