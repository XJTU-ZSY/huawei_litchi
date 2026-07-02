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
        {"nodeId": "S09"},
        {"nodeId": "S10"},
        {"nodeId": "S11"},
        {"nodeId": "S12"},
        {"nodeId": "S14"},
        {"nodeId": "S15", "terminal": True},
    ],
    "edges": [
        {"edgeId": "E1", "fromNodeId": "S01", "toNodeId": "S02", "routeType": "ROAD", "distance": 1},
        {"edgeId": "E2", "fromNodeId": "S02", "toNodeId": "S14", "routeType": "ROAD", "distance": 1},
        {"edgeId": "E3", "fromNodeId": "S14", "toNodeId": "S15", "routeType": "ROAD", "distance": 1},
        {"edgeId": "E4", "fromNodeId": "S09", "toNodeId": "S10", "routeType": "ROAD", "distance": 1},
        {"edgeId": "E5", "fromNodeId": "S10", "toNodeId": "S14", "routeType": "ROAD", "distance": 1},
        {"edgeId": "E6", "fromNodeId": "S10", "toNodeId": "S11", "routeType": "ROAD", "distance": 1},
        {"edgeId": "E7", "fromNodeId": "S11", "toNodeId": "S12", "routeType": "ROAD", "distance": 1},
        {"edgeId": "E8", "fromNodeId": "S12", "toNodeId": "S14", "routeType": "ROAD", "distance": 1},
    ],
}


def snapshot(
    memory,
    *,
    phase="NORMAL",
    nodes=None,
    tasks=None,
    contests=None,
    events=None,
    action_results=None,
    opponent_overrides=None,
    round_no=10,
    **player_overrides,
):
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
    opponent = {"playerId": 2002, "teamId": "BLUE", "state": "IDLE"}
    if opponent_overrides:
        opponent.update(opponent_overrides)
    return memory.apply_inquire(
        {
            "matchId": "m1",
            "round": round_no,
            "phase": phase,
            "players": [base_player, opponent],
            "nodes": nodes or START["nodes"],
            "tasks": tasks or [],
            "contests": contests or [],
            "events": events or [],
            "actionResults": action_results or [],
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

    def test_yields_fixed_process_to_same_node_opponent_once(self):
        memory, context, engine = self.make_engine()
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S02", "processType": "TRANSFER", "processRound": 4},
            {"nodeId": "S14"},
            {"nodeId": "S15", "terminal": True},
        ]
        snap = snapshot(
            memory,
            currentNodeId="S02",
            nodes=nodes,
            opponent_overrides={"playerId": 2002, "currentNodeId": "S02", "state": "IDLE"},
        )
        self.assertEqual(engine.decide(context, snap), [])
        self.assertIn("yield process node S02", engine.last_reason)

        retry = snapshot(
            memory,
            currentNodeId="S02",
            nodes=nodes,
            opponent_overrides={"playerId": 2002, "currentNodeId": "S02", "state": "IDLE"},
        )
        self.assertEqual(engine.decide(context, retry), [{"action": "PROCESS", "targetNodeId": "S02"}])

    def test_yields_fixed_process_while_same_node_opponent_is_busy(self):
        memory, context, engine = self.make_engine()
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S02", "processType": "TRANSFER", "processRound": 4},
            {"nodeId": "S14"},
            {"nodeId": "S15", "terminal": True},
        ]
        snap = snapshot(
            memory,
            currentNodeId="S02",
            nodes=nodes,
            opponent_overrides={"playerId": 2002, "currentNodeId": "S02", "state": "PROCESSING"},
        )
        self.assertEqual(engine.decide(context, snap), [])
        self.assertIn("wait for opponent 2002", engine.last_reason)

    def test_does_not_yield_fixed_process_to_lower_id_opponent(self):
        memory, context, engine = self.make_engine()
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S02", "processType": "TRANSFER", "processRound": 4},
            {"nodeId": "S14"},
            {"nodeId": "S15", "terminal": True},
        ]
        snap = snapshot(
            memory,
            currentNodeId="S02",
            nodes=nodes,
            opponent_overrides={"playerId": 999, "currentNodeId": "S02", "state": "IDLE"},
        )
        self.assertEqual(engine.decide(context, snap), [{"action": "PROCESS", "targetNodeId": "S02"}])

    def test_rest_completion_does_not_complete_fixed_node_process(self):
        memory, context, engine = self.make_engine()
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S02", "processType": "TRANSFER", "processRound": 4},
            {"nodeId": "S14"},
            {"nodeId": "S15", "terminal": True},
        ]
        rest_complete = {
            "type": "PROCESS_COMPLETE",
            "payload": {"playerId": 1001, "targetNodeId": "S02", "action": "REST", "objectKey": "REST:C_0001:RED"},
        }

        snap = snapshot(memory, currentNodeId="S02", nodes=nodes, events=[rest_complete])

        self.assertNotIn("S02", memory.completed_process_nodes)
        self.assertEqual(engine.decide(context, snap), [{"action": "PROCESS", "targetNodeId": "S02"}])

    def test_process_completion_marks_fixed_node_done(self):
        memory, context, engine = self.make_engine()
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S02", "processType": "TRANSFER", "processRound": 4},
            {"nodeId": "S14"},
            {"nodeId": "S15", "terminal": True},
        ]
        process_complete = {
            "type": "PROCESS_COMPLETE",
            "payload": {"playerId": 1001, "targetNodeId": "S02", "action": "PROCESS", "objectKey": "PROCESS:S02:TRANSFER"},
        }

        snap = snapshot(memory, currentNodeId="S02", nodes=nodes, events=[process_complete])

        self.assertIn("S02", memory.completed_process_nodes)
        self.assertEqual(engine.decide(context, snap), [{"action": "MOVE", "targetNodeId": "S14"}])

    def test_process_required_rejection_retries_process(self):
        memory, context, engine = self.make_engine()
        memory.completed_process_nodes.add("S02")
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S02", "processType": "TRANSFER", "processRound": 4},
            {"nodeId": "S14"},
            {"nodeId": "S15", "terminal": True},
        ]
        rejected_move = {
            "type": "ACTION_REJECTED",
            "payload": {"playerId": 1001, "action": "MOVE", "errorCode": "PROCESS_REQUIRED"},
        }

        snap = snapshot(memory, currentNodeId="S02", nodes=nodes, events=[rejected_move])

        self.assertNotIn("S02", memory.completed_process_nodes)
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

    def test_skips_resource_opponent_is_already_claiming(self):
        memory, context, engine = self.make_engine()
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S02", "resourceStock": {"ICE_BOX": 1, "FAST_HORSE": 1}},
            {"nodeId": "S14"},
            {"nodeId": "S15", "terminal": True},
        ]
        snap = snapshot(
            memory,
            currentNodeId="S02",
            nodes=nodes,
            opponent_overrides={
                "currentNodeId": "S02",
                "state": "PROCESSING",
                "currentProcess": {
                    "action": "CLAIM_RESOURCE",
                    "objectKey": "RESOURCE:S02:FAST_HORSE",
                    "targetNodeId": "S02",
                    "resourceType": "FAST_HORSE",
                    "remainRound": 1,
                },
            },
        )

        self.assertEqual(
            engine.decide(context, snap),
            [{"action": "CLAIM_RESOURCE", "targetNodeId": "S02", "resourceType": "ICE_BOX"}],
        )

    def test_does_not_claim_only_resource_opponent_is_already_claiming(self):
        memory, context, engine = self.make_engine()
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S02", "resourceStock": {"FAST_HORSE": 1}},
            {"nodeId": "S14"},
            {"nodeId": "S15", "terminal": True},
        ]
        snap = snapshot(
            memory,
            currentNodeId="S02",
            nodes=nodes,
            opponent_overrides={
                "currentNodeId": "S02",
                "state": "PROCESSING",
                "currentProcess": {
                    "action": "CLAIM_RESOURCE",
                    "objectKey": "RESOURCE:S02:FAST_HORSE",
                    "targetNodeId": "S02",
                    "resourceType": "FAST_HORSE",
                    "remainRound": 1,
                },
            },
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "MOVE", "targetNodeId": "S14"}])

    def test_endgame_preempts_optional_task_and_resource(self):
        memory, context, engine = self.make_engine()
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S09", "resourceStock": {"OFFICIAL_PERMIT": 1}},
            {"nodeId": "S10"},
            {"nodeId": "S14"},
            {"nodeId": "S15", "terminal": True},
        ]
        tasks = [{"taskId": "T02_3", "nodeId": "S09", "score": 30, "active": True}]
        snap = snapshot(memory, round_no=430, currentNodeId="S09", taskScore=60, nodes=nodes, tasks=tasks)

        self.assertEqual(engine.decide(context, snap), [{"action": "MOVE", "targetNodeId": "S10"}])
        self.assertIn("move from S09 to S10 toward S14", engine.last_reason)

    def test_endgame_processes_fixed_node_before_moving(self):
        memory, context, engine = self.make_engine()
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S10"},
            {"nodeId": "S11", "processType": "PASS_TRANSFER", "processRound": 5},
            {"nodeId": "S12"},
            {"nodeId": "S14"},
            {"nodeId": "S15", "terminal": True},
        ]
        snap = snapshot(memory, round_no=536, currentNodeId="S11", taskScore=30, nodes=nodes)

        self.assertEqual(engine.decide(context, snap), [{"action": "PROCESS", "targetNodeId": "S11"}])
        self.assertIn("process node S11", engine.last_reason)

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
