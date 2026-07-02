import unittest

from litchi_bot.graph import RouteGraph


class GraphTest(unittest.TestCase):
    def test_bidirectional_path(self):
        graph = RouteGraph.from_raw_edges(
            [
                {"edgeId": "E1", "fromNodeId": "S01", "toNodeId": "S02", "routeType": "ROAD", "distance": 1},
                {"edgeId": "E2", "fromNodeId": "S02", "toNodeId": "S03", "routeType": "ROAD", "distance": 1},
            ]
        )
        self.assertEqual(graph.shortest_path("S03", "S01"), ["S03", "S02", "S01"])

    def test_directed_path(self):
        graph = RouteGraph.from_raw_edges(
            [{"edgeId": "E1", "fromNodeId": "S01", "toNodeId": "S02", "routeType": "ROAD", "distance": 1, "bidirectional": False}]
        )
        self.assertEqual(graph.shortest_path("S02", "S01"), [])

    def test_blocked_node(self):
        graph = RouteGraph.from_raw_edges(
            [
                {"edgeId": "E1", "fromNodeId": "S01", "toNodeId": "S02", "routeType": "ROAD", "distance": 1},
                {"edgeId": "E2", "fromNodeId": "S02", "toNodeId": "S03", "routeType": "ROAD", "distance": 1},
            ]
        )
        self.assertEqual(graph.shortest_path("S01", "S03", blocked={"S02"}), [])

    def test_shortest_path_movement_rounds(self):
        graph = RouteGraph.from_raw_edges(
            [
                {"edgeId": "E1", "fromNodeId": "S01", "toNodeId": "S02", "routeType": "ROAD", "distance": 1},
                {"edgeId": "E2", "fromNodeId": "S02", "toNodeId": "S03", "routeType": "WATER", "distance": 2},
            ]
        )
        self.assertEqual(graph.shortest_path_movement_rounds("S01", "S03"), 5)


if __name__ == "__main__":
    unittest.main()
