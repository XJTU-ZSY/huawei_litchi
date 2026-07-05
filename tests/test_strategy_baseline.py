import unittest

from litchi_bot.decision import DecisionEngine
from litchi_bot.game_state import GameMemory

from tests.test_decision import START, snapshot


SQUAD_ACTIONS = {"SQUAD_SCOUT", "SQUAD_CLEAR", "SQUAD_REINFORCE", "SQUAD_WEAKEN"}
ALLOWED_ACTION_FIELDS = {
    "WAIT": {"action"},
    "MOVE": {"action", "targetNodeId"},
    "SET_GUARD": {"action", "targetNodeId", "extraGoodFruit"},
    "BREAK_GUARD": {"action", "targetNodeId", "goodFruit", "badFruit", "rushTactic"},
    "FORCED_PASS": {"action", "targetNodeId"},
    "CLEAR": {"action", "targetNodeId"},
    "SQUAD_SCOUT": {"action", "targetNodeId"},
    "SQUAD_CLEAR": {"action", "targetNodeId"},
    "SQUAD_REINFORCE": {"action", "targetNodeId"},
    "SQUAD_WEAKEN": {"action", "targetNodeId"},
    "WINDOW_CARD": {"action", "contestId", "card"},
}


def make_start(nodes=None, edges=None):
    return {
        "matchId": "m1",
        "round": 1,
        "durationRound": 600,
        "players": [{"playerId": 1001, "teamId": "RED"}, {"playerId": 2002, "teamId": "BLUE"}],
        "map": {"gameplay": {"roles": {"startNodeId": "S01", "gateNodeId": "S14", "terminalNodeIds": ["S15"]}}},
        "nodes": nodes
        or [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S02", "nodeType": "KEY_PASS"},
            {"nodeId": "S03"},
            {"nodeId": "S04"},
            {"nodeId": "S14"},
            {"nodeId": "S15", "terminal": True},
        ],
        "edges": edges
        or [
            {"edgeId": "E1", "fromNodeId": "S01", "toNodeId": "S02", "routeType": "ROAD", "distance": 1},
            {"edgeId": "E2", "fromNodeId": "S02", "toNodeId": "S14", "routeType": "ROAD", "distance": 1},
            {"edgeId": "E3", "fromNodeId": "S01", "toNodeId": "S03", "routeType": "ROAD", "distance": 1},
            {"edgeId": "E4", "fromNodeId": "S03", "toNodeId": "S14", "routeType": "ROAD", "distance": 1},
            {"edgeId": "E5", "fromNodeId": "S01", "toNodeId": "S04", "routeType": "ROAD", "distance": 1},
            {"edgeId": "E6", "fromNodeId": "S04", "toNodeId": "S14", "routeType": "ROAD", "distance": 1},
            {"edgeId": "E7", "fromNodeId": "S14", "toNodeId": "S15", "routeType": "ROAD", "distance": 1},
        ],
    }


def guard_nodes(**s02_overrides):
    s02 = {"nodeId": "S02", "nodeType": "KEY_PASS"}
    s02.update(s02_overrides)
    return [
        {"nodeId": "S01", "start": True},
        s02,
        {"nodeId": "S03"},
        {"nodeId": "S04"},
        {"nodeId": "S14"},
        {"nodeId": "S15", "terminal": True},
    ]


class BaselineGuardStrategyTest(unittest.TestCase):
    def make_engine(self, start=None):
        memory = GameMemory(1001)
        context = memory.apply_start(start or START)
        return memory, context, DecisionEngine(memory)

    def assert_protocol_safe(self, actions):
        counts = {"main": 0, "squad": 0, "window": 0}
        for action in actions:
            action_name = action.get("action")
            self.assertNotEqual(action_name, "BREAK_ORDER")
            self.assertIn(action_name, ALLOWED_ACTION_FIELDS)
            self.assertLessEqual(set(action), ALLOWED_ACTION_FIELDS[action_name])
            if action_name == "WINDOW_CARD":
                category = "window"
            elif action_name in SQUAD_ACTIONS:
                category = "squad"
            else:
                category = "main"
            counts[category] += 1
            self.assertLessEqual(counts[category], 1, actions)

    def assert_no_set_guard(self, actions):
        self.assertNotIn("SET_GUARD", [action.get("action") for action in actions])
        self.assert_protocol_safe(actions)

    def assert_no_edge_illegal_blocker_action(self, actions):
        action_names = [action.get("action") for action in actions]
        self.assertNotIn("BREAK_GUARD", action_names)
        self.assertNotIn("FORCED_PASS", action_names)
        self.assertNotIn("CLEAR", action_names)
        self.assert_protocol_safe(actions)

    def test_sets_guard_on_route_choke_without_extra_cost_when_stock_is_modest(self):
        start = make_start(nodes=guard_nodes())
        memory, context, engine = self.make_engine(start)

        snap = snapshot(
            memory,
            currentNodeId="S02",
            taskScore=90,
            goodFruit=21,
            nodes=start["nodes"],
            opponent_overrides={"currentNodeId": "S01", "state": "IDLE"},
        )

        actions = engine.decide(context, snap)
        self.assertEqual(actions, [{"action": "SET_GUARD", "targetNodeId": "S02"}])
        self.assert_protocol_safe(actions)

    def test_set_guard_eligibility_matrix_blocks_unsafe_cases(self):
        cases = [
            ("rush_phase", {"phase": "RUSH", "nodes": guard_nodes()}),
            ("below_base_task_score", {"taskScore": 89, "nodes": guard_nodes()}),
            ("safe_zone", {"nodes": guard_nodes(safeZone=True)}),
            ("node_already_has_own_guard", {"nodes": guard_nodes(guard={"ownerTeamId": "RED", "defense": 4, "active": True})}),
            ("node_already_has_enemy_guard", {"nodes": guard_nodes(guard={"ownerTeamId": "BLUE", "defense": 4, "active": True})}),
            ("ordinary_node", {"nodes": guard_nodes(nodeType="NORMAL")}),
            ("low_good_fruit", {"goodFruit": 20, "nodes": guard_nodes()}),
            (
                "opponent_route_misses_current",
                {"nodes": guard_nodes(), "opponent_overrides": {"currentNodeId": "S03", "state": "IDLE"}},
            ),
            (
                "already_two_own_guards",
                {
                    "nodes": [
                        {"nodeId": "S01", "start": True},
                        {"nodeId": "S02", "nodeType": "KEY_PASS"},
                        {"nodeId": "S03", "guard": {"ownerTeamId": "RED", "defense": 4, "active": True}},
                        {"nodeId": "S04", "guard": {"ownerTeamId": "RED", "defense": 4, "active": True}},
                        {"nodeId": "S14"},
                        {"nodeId": "S15", "terminal": True},
                    ]
                },
            ),
        ]

        for name, case in cases:
            with self.subTest(name=name):
                start = make_start(nodes=case["nodes"])
                memory, context, engine = self.make_engine(start)
                snap = snapshot(
                    memory,
                    phase=case.get("phase", "NORMAL"),
                    currentNodeId="S02",
                    taskScore=case.get("taskScore", 90),
                    goodFruit=case.get("goodFruit", 80),
                    nodes=start["nodes"],
                    opponent_overrides=case.get("opponent_overrides", {"currentNodeId": "S01", "state": "IDLE"}),
                )

                self.assert_no_set_guard(engine.decide(context, snap))

    def test_moving_uses_rejection_memory_to_reroute_instead_of_repeating_blocked_move(self):
        start = make_start(
            nodes=[
                {"nodeId": "S01", "start": True},
                {"nodeId": "S02"},
                {"nodeId": "S03"},
                {"nodeId": "S14"},
                {"nodeId": "S15", "terminal": True},
            ],
            edges=[
                {"edgeId": "E1", "fromNodeId": "S01", "toNodeId": "S02", "routeType": "ROAD", "distance": 1},
                {"edgeId": "E2", "fromNodeId": "S02", "toNodeId": "S14", "routeType": "ROAD", "distance": 1},
                {"edgeId": "E3", "fromNodeId": "S01", "toNodeId": "S03", "routeType": "ROAD", "distance": 1},
                {"edgeId": "E4", "fromNodeId": "S03", "toNodeId": "S14", "routeType": "ROAD", "distance": 1},
                {"edgeId": "E5", "fromNodeId": "S14", "toNodeId": "S15", "routeType": "ROAD", "distance": 1},
            ],
        )
        memory, context, engine = self.make_engine(start)
        result = {
            "playerId": 1001,
            "action": "MOVE",
            "targetNodeId": "S02",
            "accepted": False,
            "errorCode": "MOVE_BLOCKED_BY_GUARD",
        }

        snap = snapshot(
            memory,
            state="MOVING",
            currentNodeId="S01",
            nextNodeId="S02",
            taskScore=90,
            nodes=start["nodes"],
            action_results=[result],
        )

        actions = engine.decide(context, snap)
        self.assertIn("S02", memory.blocked_move_targets)
        self.assertEqual(actions, [{"action": "MOVE", "targetNodeId": "S03"}])
        self.assert_protocol_safe(actions)

    def test_moving_on_edge_never_breaks_or_forces_guard_even_with_budget(self):
        start = make_start(
            nodes=[
                {"nodeId": "S01", "start": True},
                {"nodeId": "S02", "guard": {"ownerTeamId": "BLUE", "defense": 1, "active": True}},
                {"nodeId": "S03"},
                {"nodeId": "S14"},
                {"nodeId": "S15", "terminal": True},
            ],
            edges=[
                {"edgeId": "E1", "fromNodeId": "S01", "toNodeId": "S02", "routeType": "ROAD", "distance": 1},
                {"edgeId": "E2", "fromNodeId": "S02", "toNodeId": "S14", "routeType": "ROAD", "distance": 1},
                {"edgeId": "E3", "fromNodeId": "S01", "toNodeId": "S03", "routeType": "ROAD", "distance": 1},
                {"edgeId": "E4", "fromNodeId": "S03", "toNodeId": "S14", "routeType": "ROAD", "distance": 1},
                {"edgeId": "E5", "fromNodeId": "S14", "toNodeId": "S15", "routeType": "ROAD", "distance": 1},
            ],
        )
        memory, context, engine = self.make_engine(start)

        snap = snapshot(
            memory,
            state="MOVING",
            currentNodeId="S01",
            nextNodeId="S02",
            taskScore=90,
            goodFruit=100,
            badFruit=2,
            nodes=start["nodes"],
        )

        actions = engine.decide(context, snap)
        self.assertEqual(actions, [{"action": "MOVE", "targetNodeId": "S03"}])
        self.assert_no_edge_illegal_blocker_action(actions)

    def test_moving_waits_when_rejection_memory_blocks_target_without_safe_reroute(self):
        memory, context, engine = self.make_engine()
        result = {
            "playerId": 1001,
            "action": "MOVE",
            "targetNodeId": "S02",
            "accepted": False,
            "errorCode": "MOVE_BLOCKED_BY_GUARD",
        }

        snap = snapshot(
            memory,
            state="MOVING",
            currentNodeId="S01",
            nextNodeId="S02",
            taskScore=90,
            action_results=[result],
        )

        actions = engine.decide(context, snap)
        self.assertEqual(actions, [{"action": "WAIT"}])
        self.assert_protocol_safe(actions)

    def test_edge_reroute_skips_blocked_alternate_neighbor(self):
        start = make_start(
            nodes=[
                {"nodeId": "S01", "start": True},
                {"nodeId": "S02", "guard": {"ownerTeamId": "BLUE", "defense": 4, "active": True}},
                {"nodeId": "S03", "hasObstacle": True},
                {"nodeId": "S04"},
                {"nodeId": "S14"},
                {"nodeId": "S15", "terminal": True},
            ]
        )
        memory, context, engine = self.make_engine(start)

        snap = snapshot(
            memory,
            state="MOVING",
            currentNodeId="S01",
            nextNodeId="S02",
            taskScore=90,
            nodes=start["nodes"],
        )

        actions = engine.decide(context, snap)
        self.assertEqual(actions, [{"action": "MOVE", "targetNodeId": "S04"}])
        self.assert_protocol_safe(actions)

    def test_edge_blocked_target_waits_when_all_alternates_are_blocked_or_unreachable(self):
        start = make_start(
            nodes=[
                {"nodeId": "S01", "start": True},
                {"nodeId": "S02", "guard": {"ownerTeamId": "BLUE", "defense": 4, "active": True}},
                {"nodeId": "S03", "hasObstacle": True},
                {"nodeId": "S04"},
                {"nodeId": "S14"},
                {"nodeId": "S15", "terminal": True},
            ],
            edges=[
                {"edgeId": "E1", "fromNodeId": "S01", "toNodeId": "S02", "routeType": "ROAD", "distance": 1},
                {"edgeId": "E2", "fromNodeId": "S02", "toNodeId": "S14", "routeType": "ROAD", "distance": 1},
                {"edgeId": "E3", "fromNodeId": "S01", "toNodeId": "S03", "routeType": "ROAD", "distance": 1},
                {"edgeId": "E4", "fromNodeId": "S03", "toNodeId": "S14", "routeType": "ROAD", "distance": 1},
                {"edgeId": "E5", "fromNodeId": "S01", "toNodeId": "S04", "routeType": "ROAD", "distance": 1},
                {"edgeId": "E6", "fromNodeId": "S14", "toNodeId": "S15", "routeType": "ROAD", "distance": 1},
            ],
        )
        memory, context, engine = self.make_engine(start)

        snap = snapshot(
            memory,
            state="MOVING",
            currentNodeId="S01",
            nextNodeId="S02",
            taskScore=90,
            nodes=start["nodes"],
        )

        actions = engine.decide(context, snap)
        self.assertEqual(actions, [{"action": "WAIT"}])
        self.assert_protocol_safe(actions)

    def test_idle_clears_adjacent_obstacle_and_does_not_duplicate_squad_clear(self):
        memory, context, engine = self.make_engine()
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S02", "hasObstacle": True},
            {"nodeId": "S14"},
            {"nodeId": "S15", "terminal": True},
        ]

        snap = snapshot(memory, currentNodeId="S01", taskScore=90, goodFruit=30, squadAvailable=8, nodes=nodes)

        actions = engine.decide(context, snap)
        self.assertEqual(actions, [{"action": "CLEAR", "targetNodeId": "S02"}])
        self.assert_protocol_safe(actions)

    def test_idle_break_guard_does_not_duplicate_squad_weaken(self):
        memory, context, engine = self.make_engine()
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S02", "guard": {"ownerTeamId": "BLUE", "defense": 3, "active": True}},
            {"nodeId": "S14"},
            {"nodeId": "S15", "terminal": True},
        ]

        snap = snapshot(memory, currentNodeId="S01", taskScore=90, badFruit=1, squadAvailable=8, nodes=nodes)

        actions = engine.decide(context, snap)
        self.assertEqual(actions, [{"action": "BREAK_GUARD", "targetNodeId": "S02", "badFruit": 1}])
        self.assert_protocol_safe(actions)

    def test_idle_sends_squad_weaken_for_downstream_guard_not_handled_by_main(self):
        start = make_start(
            nodes=[
                {"nodeId": "S01", "start": True},
                {"nodeId": "S02"},
                {"nodeId": "S03", "guard": {"ownerTeamId": "BLUE", "defense": 4, "active": True}},
                {"nodeId": "S14"},
                {"nodeId": "S15", "terminal": True},
            ],
            edges=[
                {"edgeId": "E1", "fromNodeId": "S01", "toNodeId": "S02", "routeType": "ROAD", "distance": 1},
                {"edgeId": "E2", "fromNodeId": "S02", "toNodeId": "S03", "routeType": "ROAD", "distance": 1},
                {"edgeId": "E3", "fromNodeId": "S03", "toNodeId": "S14", "routeType": "ROAD", "distance": 1},
                {"edgeId": "E4", "fromNodeId": "S14", "toNodeId": "S15", "routeType": "ROAD", "distance": 1},
            ],
        )
        memory, context, engine = self.make_engine(start)

        snap = snapshot(memory, currentNodeId="S01", taskScore=90, squadAvailable=2, nodes=start["nodes"])

        actions = engine.decide(context, snap)
        self.assertEqual(
            actions,
            [{"action": "MOVE", "targetNodeId": "S02"}, {"action": "SQUAD_WEAKEN", "targetNodeId": "S03"}],
        )
        self.assert_protocol_safe(actions)

    def test_guard_threat_from_opponent_processing_set_guard_is_avoided_when_alternative_exists(self):
        start = make_start(
            edges=[
                {"edgeId": "E1", "fromNodeId": "S01", "toNodeId": "S02", "routeType": "ROAD", "distance": 2},
                {"edgeId": "E2", "fromNodeId": "S02", "toNodeId": "S14", "routeType": "ROAD", "distance": 1},
                {"edgeId": "E3", "fromNodeId": "S01", "toNodeId": "S03", "routeType": "ROAD", "distance": 3},
                {"edgeId": "E4", "fromNodeId": "S03", "toNodeId": "S14", "routeType": "ROAD", "distance": 1},
                {"edgeId": "E5", "fromNodeId": "S14", "toNodeId": "S15", "routeType": "ROAD", "distance": 1},
            ]
        )
        memory, context, engine = self.make_engine(start)

        snap = snapshot(
            memory,
            currentNodeId="S01",
            taskScore=90,
            nodes=start["nodes"],
            opponent_overrides={
                "currentNodeId": "S09",
                "state": "PROCESSING",
                "currentProcess": {"action": "SET_GUARD", "targetNodeId": "S02", "remainRound": 1},
            },
        )

        actions = engine.decide(context, snap)
        self.assertEqual(actions, [{"action": "MOVE", "targetNodeId": "S03"}])
        self.assert_protocol_safe(actions)

    def test_guard_threat_falls_back_to_original_route_without_alternative(self):
        memory, context, engine = self.make_engine()

        snap = snapshot(
            memory,
            currentNodeId="S01",
            taskScore=90,
            opponent_overrides={
                "currentNodeId": "S09",
                "state": "PROCESSING",
                "currentProcess": {"action": "SET_GUARD", "targetNodeId": "S02", "remainRound": 1},
            },
        )

        actions = engine.decide(context, snap)
        self.assertEqual(actions, [{"action": "MOVE", "targetNodeId": "S02"}])
        self.assert_protocol_safe(actions)


if __name__ == "__main__":
    unittest.main()
