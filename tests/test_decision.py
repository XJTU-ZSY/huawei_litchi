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


def snapshot(memory, **player_overrides):
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
            "phase": "NORMAL",
            "players": [base_player, {"playerId": 2002, "teamId": "BLUE", "state": "IDLE"}],
            "nodes": START["nodes"],
            "tasks": [],
            "contests": [],
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

    def test_moving_continues_to_next_node(self):
        memory, context, engine = self.make_engine()
        snap = snapshot(memory, state="MOVING", currentNodeId="S01", nextNodeId="S02")
        self.assertEqual(engine.decide(context, snap), [{"action": "MOVE", "targetNodeId": "S02"}])

    def test_gate_verification_in_rush(self):
        memory, context, engine = self.make_engine()
        snap = snapshot(memory, currentNodeId="S14")
        snap.phase = "RUSH"
        self.assertEqual(engine.decide(context, snap), [{"action": "VERIFY_GATE"}])

    def test_terminal_delivery_when_verified(self):
        memory, context, engine = self.make_engine()
        snap = snapshot(memory, currentNodeId="S15", verified=True)
        self.assertEqual(engine.decide(context, snap), [{"action": "DELIVER"}])

    def test_claim_current_task(self):
        memory, context, engine = self.make_engine()
        snap = memory.apply_inquire(
            {
                "matchId": "m1",
                "round": 10,
                "phase": "NORMAL",
                "players": [
                    {
                        "playerId": 1001,
                        "teamId": "RED",
                        "state": "IDLE",
                        "currentNodeId": "S02",
                        "freshness": 100,
                        "goodFruit": 100,
                        "taskScore": 0,
                        "verified": False,
                        "delivered": False,
                        "resources": {},
                        "buffs": [],
                        "guardActionPoint": 4,
                    }
                ],
                "nodes": START["nodes"],
                "tasks": [{"taskId": "T01_1", "nodeId": "S02", "score": 30, "active": True}],
                "contests": [],
                "events": [],
                "actionResults": [],
            }
        )
        self.assertEqual(engine.decide(context, snap), [{"action": "CLAIM_TASK", "taskId": "T01_1"}])


if __name__ == "__main__":
    unittest.main()
