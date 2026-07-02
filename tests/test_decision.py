import unittest

from litchi_bot.decision import DecisionEngine
from litchi_bot.game_state import GameMemory


START = {
    "matchId": "m1",
    "round": 1,
    "durationRound": 600,
    "players": [{"playerId": 1001, "teamId": "RED"}, {"playerId": 2002, "teamId": "BLUE"}],
    "map": {"gameplay": {"roles": {"startNodeId": "S01", "gateNodeId": "S14", "terminalNodeIds": ["S15"]}}},
    "nodes": [
        {"nodeId": "S01", "start": True},
        {"nodeId": "S02"},
        {"nodeId": "S14"},
        {"nodeId": "S15", "terminal": True},
    ],
    "edges": [
        {"edgeId": "E1", "fromNodeId": "S01", "toNodeId": "S02", "routeType": "ROAD", "distance": 1},
        {"edgeId": "E2", "fromNodeId": "S02", "toNodeId": "S14", "routeType": "ROAD", "distance": 1},
        {"edgeId": "E3", "fromNodeId": "S14", "toNodeId": "S15", "routeType": "ROAD", "distance": 1},
    ],
}


def snapshot(memory, *, phase="NORMAL", nodes=None, tasks=None, contests=None, **player_overrides):
    base_player = {
        "playerId": 1001,
        "teamId": "RED",
        "state": "IDLE",
        "currentNodeId": "S01",
        "nextNodeId": None,
        "freshness": 100,
        "goodFruit": 100,
        "taskScore": 0,
        "verified": False,
        "delivered": False,
        "resources": {},
        "buffs": [],
        "guardActionPoint": 4,
    }
    base_player.update(player_overrides)
    return memory.apply_inquire(
        {
            "matchId": "m1",
            "round": 10,
            "phase": phase,
            "players": [base_player, {"playerId": 2002, "teamId": "BLUE", "state": "IDLE"}],
            "nodes": nodes or START["nodes"],
            "tasks": tasks or [],
            "contests": contests or [],
            "events": [],
            "actionResults": [],
        }
    )


class DecisionTest(unittest.TestCase):
    def make_engine(self):
        memory = GameMemory(1001)
        context = memory.apply_start(START)
        return memory, context, DecisionEngine(memory)

    def test_delivered_returns_no_actions(self):
        memory, context, engine = self.make_engine()
        snap = snapshot(memory, state="DELIVERED", delivered=True)
        self.assertEqual(engine.decide(context, snap), [])

    def test_processing_returns_no_main_action(self):
        memory, context, engine = self.make_engine()
        snap = snapshot(memory, state="PROCESSING")
        self.assertEqual(engine.decide(context, snap), [])

    def test_busy_states_return_no_main_action(self):
        for state in ("VERIFYING", "RESTING", "FORCED_PASSING"):
            with self.subTest(state=state):
                memory, context, engine = self.make_engine()
                snap = snapshot(memory, state=state)
                self.assertEqual(engine.decide(context, snap), [])

    def test_moving_continues_to_next_node(self):
        memory, context, engine = self.make_engine()
        snap = snapshot(memory, state="MOVING", currentNodeId="S01", nextNodeId="S02")
        self.assertEqual(engine.decide(context, snap), [{"action": "MOVE", "targetNodeId": "S02"}])

    def test_waiting_without_next_node_returns_no_action(self):
        memory, context, engine = self.make_engine()
        snap = snapshot(memory, state="WAITING", currentNodeId="S01", nextNodeId=None)
        self.assertEqual(engine.decide(context, snap), [])

    def test_gate_verification_in_rush(self):
        memory, context, engine = self.make_engine()
        snap = snapshot(memory, phase="RUSH", currentNodeId="S14")
        self.assertEqual(engine.decide(context, snap), [{"action": "VERIFY_GATE"}])

    def test_terminal_delivery_when_verified(self):
        memory, context, engine = self.make_engine()
        snap = snapshot(memory, currentNodeId="S15", verified=True)
        self.assertEqual(engine.decide(context, snap), [{"action": "DELIVER"}])

    def test_terminal_without_verification_returns_to_gate(self):
        memory, context, engine = self.make_engine()
        snap = snapshot(memory, currentNodeId="S15", verified=False)
        self.assertEqual(engine.decide(context, snap), [{"action": "MOVE", "targetNodeId": "S14"}])

    def test_claim_current_task(self):
        memory, context, engine = self.make_engine()
        snap = snapshot(memory, currentNodeId="S02", tasks=[{"taskId": "T01_1", "nodeId": "S02", "score": 30, "active": True}])
        self.assertEqual(engine.decide(context, snap), [{"action": "CLAIM_TASK", "taskId": "T01_1"}])

    def test_process_current_node_before_moving(self):
        memory, context, engine = self.make_engine()
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S02", "processType": "BOARD", "processRound": 3},
            {"nodeId": "S14"},
            {"nodeId": "S15", "terminal": True},
        ]
        snap = snapshot(memory, currentNodeId="S02", nodes=nodes)
        self.assertEqual(engine.decide(context, snap), [{"action": "PROCESS", "targetNodeId": "S02"}])

    def test_claim_current_resource_by_priority(self):
        memory, context, engine = self.make_engine()
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S02", "resourceStock": {"ICE_BOX": 1, "FAST_HORSE": 1}},
            {"nodeId": "S14"},
            {"nodeId": "S15", "terminal": True},
        ]
        snap = snapshot(memory, currentNodeId="S02", nodes=nodes)
        self.assertEqual(
            engine.decide(context, snap),
            [{"action": "CLAIM_RESOURCE", "targetNodeId": "S02", "resourceType": "FAST_HORSE"}],
        )

    def test_contesting_state_only_sends_window_card(self):
        memory, context, engine = self.make_engine()
        contests = [{"contestId": "C1", "contestType": "TASK", "redPlayerId": 1001, "bluePlayerId": 2002, "roundIndex": 1}]
        snap = snapshot(memory, state="CONTESTING", currentNodeId="S02", contests=contests)
        self.assertEqual(engine.decide(context, snap), [{"action": "WINDOW_CARD", "contestId": "C1", "card": "BING_ZHENG"}])

    def test_suppressed_contest_is_ignored(self):
        memory, context, engine = self.make_engine()
        contests = [{"contestId": "C1", "contestType": "TASK", "redPlayerId": 1001, "status": "SUPPRESSED"}]
        snap = snapshot(memory, state="CONTESTING", currentNodeId="S02", contests=contests)
        self.assertEqual(engine.decide(context, snap), [])

    def test_decision_exception_falls_back_to_empty_actions(self):
        memory, context, engine = self.make_engine()

        def raise_error(_context, _snapshot):
            raise RuntimeError("boom")

        engine.strategy.decide = raise_error
        self.assertEqual(engine.decide(context, snapshot(memory)), [])
        self.assertIn("decision exception", engine.last_reason)


if __name__ == "__main__":
    unittest.main()
