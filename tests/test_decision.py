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
        {"nodeId": "S07"},
        {"nodeId": "S09"},
        {"nodeId": "S13"},
        {"nodeId": "S14"},
        {"nodeId": "S15", "terminal": True},
    ],
    "edges": [
        {"edgeId": "E1", "fromNodeId": "S01", "toNodeId": "S02", "routeType": "ROAD", "distance": 1},
        {"edgeId": "E2", "fromNodeId": "S02", "toNodeId": "S14", "routeType": "ROAD", "distance": 1},
        {"edgeId": "E3", "fromNodeId": "S14", "toNodeId": "S15", "routeType": "ROAD", "distance": 1},
        {"edgeId": "E4", "fromNodeId": "S13", "toNodeId": "S14", "routeType": "ROAD", "distance": 1},
        {"edgeId": "E5", "fromNodeId": "S07", "toNodeId": "S09", "routeType": "ROAD", "distance": 1},
    ],
    "taskTemplates": [{"taskTemplateId": "T06", "requiredResourceTypes": ["FAST_HORSE"]}],
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

    def test_gate_verification_binds_break_order_when_bad_fruit_can_pay(self):
        memory, context, engine = self.make_engine()
        snap = snapshot(memory, phase="RUSH", currentNodeId="S14", badFruit=2, rushTacticUsedCount=0)
        self.assertEqual(
            engine.decide(context, snap),
            [{"action": "VERIFY_GATE", "targetNodeId": "S14", "rushTactic": "BREAK_ORDER"}],
        )
        self.assertIn("BREAK_ORDER", engine.last_reason)

    def test_gate_verification_does_not_bind_break_order_without_bad_fruit(self):
        memory, context, engine = self.make_engine()
        snap = snapshot(memory, phase="RUSH", currentNodeId="S14", badFruit=1, rushTacticUsedCount=0)
        self.assertEqual(engine.decide(context, snap), [{"action": "VERIFY_GATE"}])

    def test_gate_verification_does_not_bind_break_order_after_rush_tactic_used(self):
        memory, context, engine = self.make_engine()
        snap = snapshot(memory, phase="RUSH", currentNodeId="S14", badFruit=2, rushTacticUsedCount=1)
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

    def test_claims_required_resource_before_current_task(self):
        memory, context, engine = self.make_engine()
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S02", "resourceStock": {"FAST_HORSE": 1}},
            {"nodeId": "S14"},
            {"nodeId": "S15", "terminal": True},
        ]
        tasks = [
            {
                "taskId": "T06_006",
                "taskTemplateId": "T06",
                "nodeId": "S02",
                "score": 30,
                "active": True,
            }
        ]
        self.assertEqual(
            engine.decide(context, snapshot(memory, currentNodeId="S02", nodes=nodes, tasks=tasks)),
            [{"action": "CLAIM_RESOURCE", "targetNodeId": "S02", "resourceType": "FAST_HORSE"}],
        )
        self.assertIn("claim required horse resource FAST_HORSE", engine.last_reason)

    def test_short_horse_satisfies_horse_transfer_task(self):
        memory, context, engine = self.make_engine()
        tasks = [
            {
                "taskId": "T06_006",
                "taskTemplateId": "T06",
                "nodeId": "S02",
                "score": 30,
                "active": True,
            }
        ]

        self.assertEqual(
            engine.decide(context, snapshot(memory, currentNodeId="S02", resources={"SHORT_HORSE": 1}, tasks=tasks)),
            [{"action": "CLAIM_TASK", "taskId": "T06_006"}],
        )
        self.assertIn("claim current task T06_006", engine.last_reason)

    def test_claims_short_horse_for_horse_transfer_when_fast_horse_unavailable(self):
        memory, context, engine = self.make_engine()
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S02", "resourceStock": {"SHORT_HORSE": 1}},
            {"nodeId": "S14"},
            {"nodeId": "S15", "terminal": True},
        ]
        tasks = [
            {
                "taskId": "T06_006",
                "taskTemplateId": "T06",
                "nodeId": "S02",
                "score": 30,
                "active": True,
            }
        ]

        self.assertEqual(
            engine.decide(context, snapshot(memory, currentNodeId="S02", nodes=nodes, tasks=tasks)),
            [{"action": "CLAIM_RESOURCE", "targetNodeId": "S02", "resourceType": "SHORT_HORSE"}],
        )
        self.assertIn("claim required horse resource SHORT_HORSE", engine.last_reason)

    def test_claims_route_enabling_horse_before_equal_current_task(self):
        memory, context, engine = self.make_engine()
        nodes = [
            {"nodeId": "S07", "resourceStock": {"SHORT_HORSE": 1}},
            {"nodeId": "S09"},
            {"nodeId": "S14"},
            {"nodeId": "S15", "terminal": True},
        ]
        tasks = [
            {"taskId": "T02_002", "nodeId": "S07", "score": 30, "active": True},
            {
                "taskId": "T06_006",
                "taskTemplateId": "T06",
                "nodeId": "S09",
                "processType": "HORSE_TRANSFER",
                "score": 30,
                "active": True,
            },
        ]

        self.assertEqual(
            engine.decide(context, snapshot(memory, currentNodeId="S07", taskScore=30, nodes=nodes, tasks=tasks)),
            [{"action": "CLAIM_RESOURCE", "targetNodeId": "S07", "resourceType": "SHORT_HORSE"}],
        )
        self.assertIn("claim route-enabling SHORT_HORSE", engine.last_reason)

    def test_task_destination_uses_movement_rounds_not_hop_count(self):
        start = {
            "matchId": "m1",
            "round": 1,
            "durationRound": 600,
            "players": [{"playerId": 1001, "teamId": "RED"}, {"playerId": 2002, "teamId": "BLUE"}],
            "map": {"gameplay": {"roles": {"startNodeId": "S01", "gateNodeId": "S14", "terminalNodeIds": ["S15"]}}},
            "nodes": [
                {"nodeId": "S02"},
                {"nodeId": "S03"},
                {"nodeId": "S04"},
                {"nodeId": "S07"},
                {"nodeId": "S14"},
                {"nodeId": "S15", "terminal": True},
            ],
            "edges": [
                {"edgeId": "E1", "fromNodeId": "S03", "toNodeId": "S07", "routeType": "ROAD", "distance": 54},
                {"edgeId": "E2", "fromNodeId": "S03", "toNodeId": "S02", "routeType": "ROAD", "distance": 25},
                {"edgeId": "E3", "fromNodeId": "S02", "toNodeId": "S04", "routeType": "ROAD", "distance": 20},
                {"edgeId": "E4", "fromNodeId": "S04", "toNodeId": "S14", "routeType": "ROAD", "distance": 1},
                {"edgeId": "E5", "fromNodeId": "S14", "toNodeId": "S15", "routeType": "ROAD", "distance": 1},
            ],
        }
        memory = GameMemory(1001)
        context = memory.apply_start(start)
        engine = DecisionEngine(memory)
        tasks = [
            {"taskId": "T02_002", "nodeId": "S07", "score": 30, "active": True},
            {"taskId": "T08_008", "nodeId": "S04", "score": 30, "active": True},
        ]

        self.assertEqual(
            engine.decide(context, snapshot(memory, currentNodeId="S03", nodes=start["nodes"], tasks=tasks)),
            [{"action": "MOVE", "targetNodeId": "S02"}],
        )
        self.assertIn("toward S04", engine.last_reason)

    def test_skips_current_task_when_required_resource_unavailable(self):
        memory, context, engine = self.make_engine()
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S02", "resourceStock": {"FAST_HORSE": 0}},
            {"nodeId": "S14"},
            {"nodeId": "S15", "terminal": True},
        ]
        tasks = [
            {
                "taskId": "T06_006",
                "taskTemplateId": "T06",
                "nodeId": "S02",
                "score": 30,
                "active": True,
            }
        ]
        self.assertEqual(
            engine.decide(context, snapshot(memory, currentNodeId="S02", nodes=nodes, tasks=tasks)),
            [{"action": "MOVE", "targetNodeId": "S14"}],
        )
        self.assertNotEqual(engine.last_reason, "claim current task T06_006")

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

    def test_claims_equal_value_current_task_before_downstream_route_task_after_base_score(self):
        start = {
            "matchId": "m1",
            "round": 1,
            "durationRound": 600,
            "players": [{"playerId": 1001, "teamId": "RED"}, {"playerId": 2002, "teamId": "BLUE"}],
            "map": {"gameplay": {"roles": {"startNodeId": "S01", "gateNodeId": "S14", "terminalNodeIds": ["S15"]}}},
            "nodes": [
                {"nodeId": "S11", "processType": "PASS_TRANSFER", "processRound": 5},
                {"nodeId": "S12"},
                {"nodeId": "S13", "processType": "PALACE_TRANSFER", "processRound": 5},
                {"nodeId": "S14"},
                {"nodeId": "S15", "terminal": True},
            ],
            "edges": [
                {"edgeId": "E1", "fromNodeId": "S11", "toNodeId": "S12", "routeType": "ROAD", "distance": 1},
                {"edgeId": "E2", "fromNodeId": "S12", "toNodeId": "S13", "routeType": "ROAD", "distance": 1},
                {"edgeId": "E3", "fromNodeId": "S13", "toNodeId": "S14", "routeType": "ROAD", "distance": 1},
                {"edgeId": "E4", "fromNodeId": "S14", "toNodeId": "S15", "routeType": "ROAD", "distance": 1},
            ],
        }
        memory = GameMemory(1001)
        context = memory.apply_start(start)
        engine = DecisionEngine(memory)
        tasks = [
            {"taskId": "DONE_1", "nodeId": "S04", "score": 30, "completed": True, "ownerPlayerId": 1001},
            {"taskId": "DONE_2", "nodeId": "S05", "score": 30, "completed": True, "ownerPlayerId": 1001},
            {"taskId": "DONE_3", "nodeId": "S10", "score": 30, "completed": True, "ownerPlayerId": 1001},
            {"taskId": "T12_012", "nodeId": "S11", "score": 15, "processRound": 5, "active": True},
            {"taskId": "T13_013", "nodeId": "S13", "score": 15, "processRound": 5, "active": True},
        ]

        self.assertEqual(
            engine.decide(context, snapshot(memory, currentNodeId="S11", taskScore=80, nodes=start["nodes"], tasks=tasks)),
            [{"action": "CLAIM_TASK", "taskId": "T12_012"}],
        )

    def test_defers_low_value_current_task_for_higher_downstream_route_task_after_base_score(self):
        start = {
            "matchId": "m1",
            "round": 1,
            "durationRound": 600,
            "players": [{"playerId": 1001, "teamId": "RED"}, {"playerId": 2002, "teamId": "BLUE"}],
            "map": {"gameplay": {"roles": {"startNodeId": "S01", "gateNodeId": "S14", "terminalNodeIds": ["S15"]}}},
            "nodes": [
                {"nodeId": "S11", "processType": "PASS_TRANSFER", "processRound": 5},
                {"nodeId": "S12"},
                {"nodeId": "S13", "processType": "PALACE_TRANSFER", "processRound": 5},
                {"nodeId": "S14"},
                {"nodeId": "S15", "terminal": True},
            ],
            "edges": [
                {"edgeId": "E1", "fromNodeId": "S11", "toNodeId": "S12", "routeType": "ROAD", "distance": 1},
                {"edgeId": "E2", "fromNodeId": "S12", "toNodeId": "S13", "routeType": "ROAD", "distance": 1},
                {"edgeId": "E3", "fromNodeId": "S13", "toNodeId": "S14", "routeType": "ROAD", "distance": 1},
                {"edgeId": "E4", "fromNodeId": "S14", "toNodeId": "S15", "routeType": "ROAD", "distance": 1},
            ],
        }
        memory = GameMemory(1001)
        context = memory.apply_start(start)
        engine = DecisionEngine(memory)
        tasks = [
            {"taskId": "DONE_1", "nodeId": "S04", "score": 30, "completed": True, "ownerPlayerId": 1001},
            {"taskId": "DONE_2", "nodeId": "S05", "score": 30, "completed": True, "ownerPlayerId": 1001},
            {"taskId": "DONE_3", "nodeId": "S10", "score": 30, "completed": True, "ownerPlayerId": 1001},
            {"taskId": "T12_012", "nodeId": "S11", "score": 15, "processRound": 5, "active": True},
            {"taskId": "T02_013", "nodeId": "S13", "score": 30, "processRound": 4, "active": True},
        ]

        self.assertEqual(
            engine.decide(context, snapshot(memory, currentNodeId="S11", taskScore=80, nodes=start["nodes"], tasks=tasks)),
            [{"action": "PROCESS", "targetNodeId": "S11"}],
        )

    def test_low_value_current_task_not_deferred_before_base_score(self):
        start = {
            "matchId": "m1",
            "round": 1,
            "durationRound": 600,
            "players": [{"playerId": 1001, "teamId": "RED"}, {"playerId": 2002, "teamId": "BLUE"}],
            "map": {"gameplay": {"roles": {"startNodeId": "S01", "gateNodeId": "S14", "terminalNodeIds": ["S15"]}}},
            "nodes": [
                {"nodeId": "S11", "processType": "PASS_TRANSFER", "processRound": 5},
                {"nodeId": "S12"},
                {"nodeId": "S13"},
                {"nodeId": "S14"},
                {"nodeId": "S15", "terminal": True},
            ],
            "edges": [
                {"edgeId": "E1", "fromNodeId": "S11", "toNodeId": "S12", "routeType": "ROAD", "distance": 1},
                {"edgeId": "E2", "fromNodeId": "S12", "toNodeId": "S13", "routeType": "ROAD", "distance": 1},
                {"edgeId": "E3", "fromNodeId": "S13", "toNodeId": "S14", "routeType": "ROAD", "distance": 1},
                {"edgeId": "E4", "fromNodeId": "S14", "toNodeId": "S15", "routeType": "ROAD", "distance": 1},
            ],
        }
        memory = GameMemory(1001)
        context = memory.apply_start(start)
        engine = DecisionEngine(memory)
        tasks = [
            {"taskId": "T12_012", "nodeId": "S11", "score": 15, "processRound": 5, "active": True},
            {"taskId": "T13_013", "nodeId": "S13", "score": 15, "processRound": 5, "active": True},
        ]

        self.assertEqual(
            engine.decide(context, snapshot(memory, currentNodeId="S11", nodes=start["nodes"], tasks=tasks)),
            [{"action": "CLAIM_TASK", "taskId": "T12_012"}],
        )

    def test_high_value_current_task_not_deferred_for_downstream_task(self):
        start = {
            "matchId": "m1",
            "round": 1,
            "durationRound": 600,
            "players": [{"playerId": 1001, "teamId": "RED"}, {"playerId": 2002, "teamId": "BLUE"}],
            "map": {"gameplay": {"roles": {"startNodeId": "S01", "gateNodeId": "S14", "terminalNodeIds": ["S15"]}}},
            "nodes": [
                {"nodeId": "S11", "processType": "PASS_TRANSFER", "processRound": 5},
                {"nodeId": "S12"},
                {"nodeId": "S13"},
                {"nodeId": "S14"},
                {"nodeId": "S15", "terminal": True},
            ],
            "edges": [
                {"edgeId": "E1", "fromNodeId": "S11", "toNodeId": "S12", "routeType": "ROAD", "distance": 1},
                {"edgeId": "E2", "fromNodeId": "S12", "toNodeId": "S13", "routeType": "ROAD", "distance": 1},
                {"edgeId": "E3", "fromNodeId": "S13", "toNodeId": "S14", "routeType": "ROAD", "distance": 1},
                {"edgeId": "E4", "fromNodeId": "S14", "toNodeId": "S15", "routeType": "ROAD", "distance": 1},
            ],
        }
        memory = GameMemory(1001)
        context = memory.apply_start(start)
        engine = DecisionEngine(memory)
        tasks = [
            {"taskId": "DONE_1", "nodeId": "S04", "score": 30, "completed": True, "ownerPlayerId": 1001},
            {"taskId": "DONE_2", "nodeId": "S05", "score": 30, "completed": True, "ownerPlayerId": 1001},
            {"taskId": "DONE_3", "nodeId": "S10", "score": 30, "completed": True, "ownerPlayerId": 1001},
            {"taskId": "T02_012", "nodeId": "S11", "score": 30, "processRound": 4, "active": True},
            {"taskId": "T11_013", "nodeId": "S13", "score": 30, "processRound": 4, "active": True},
        ]

        self.assertEqual(
            engine.decide(context, snapshot(memory, currentNodeId="S11", taskScore=90, nodes=start["nodes"], tasks=tasks)),
            [{"action": "CLAIM_TASK", "taskId": "T02_012"}],
        )

    def test_claims_required_current_resource_before_process_when_safe(self):
        memory, context, engine = self.make_engine()
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S02", "processType": "BOARD", "processRound": 3, "resourceStock": {"FAST_HORSE": 1}},
            {"nodeId": "S14"},
            {"nodeId": "S15", "terminal": True},
        ]
        tasks = [
            {
                "taskId": "T06_006",
                "taskTemplateId": "T06",
                "nodeId": "S02",
                "score": 30,
                "active": True,
            }
        ]

        self.assertEqual(
            engine.decide(context, snapshot(memory, currentNodeId="S02", nodes=nodes, tasks=tasks)),
            [{"action": "CLAIM_RESOURCE", "targetNodeId": "S02", "resourceType": "FAST_HORSE"}],
        )
        self.assertIn("before process S02", engine.last_reason)

    def test_required_current_resource_before_process_avoids_idle_opponent_contest(self):
        memory, context, engine = self.make_engine()
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S02", "processType": "BOARD", "processRound": 3, "resourceStock": {"FAST_HORSE": 1}},
            {"nodeId": "S14"},
            {"nodeId": "S15", "terminal": True},
        ]
        tasks = [
            {
                "taskId": "T06_006",
                "taskTemplateId": "T06",
                "nodeId": "S02",
                "score": 30,
                "active": True,
            }
        ]

        action = engine.decide(
            context,
            snapshot(
                memory,
                currentNodeId="S02",
                nodes=nodes,
                tasks=tasks,
                opponent_overrides={"currentNodeId": "S02", "state": "IDLE"},
            ),
        )

        self.assertNotEqual(action, [{"action": "CLAIM_RESOURCE", "targetNodeId": "S02", "resourceType": "FAST_HORSE"}])

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
            taskScore=90,
            nodes=nodes,
            opponent_overrides={"playerId": 2002, "currentNodeId": "S02", "state": "IDLE"},
        )
        self.assertEqual(engine.decide(context, snap), [])
        self.assertIn("yield process node S02", engine.last_reason)

        retry = snapshot(
            memory,
            currentNodeId="S02",
            taskScore=90,
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
            taskScore=90,
            nodes=nodes,
            opponent_overrides={"playerId": 2002, "currentNodeId": "S02", "state": "PROCESSING"},
        )
        self.assertEqual(engine.decide(context, snap), [])
        self.assertIn("wait for opponent 2002", engine.last_reason)

    def test_desyncs_early_fixed_process_without_current_task_against_idle_opponent(self):
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
            taskScore=0,
            nodes=nodes,
            opponent_overrides={"playerId": 2002, "currentNodeId": "S02", "state": "IDLE"},
        )

        self.assertEqual(engine.decide(context, snap), [])
        self.assertIn("yield process node S02", engine.last_reason)

        retry = snapshot(
            memory,
            currentNodeId="S02",
            taskScore=0,
            nodes=nodes,
            opponent_overrides={"playerId": 2002, "currentNodeId": "S02", "state": "PROCESSING"},
        )

        self.assertEqual(engine.decide(context, retry), [{"action": "PROCESS", "targetNodeId": "S02"}])
        self.assertIn("process node S02", engine.last_reason)

    def test_competes_for_early_fixed_process_when_downstream_task_is_reachable(self):
        start = {
            "matchId": "m1",
            "round": 1,
            "durationRound": 600,
            "players": [{"playerId": 1001, "teamId": "RED"}, {"playerId": 2002, "teamId": "BLUE"}],
            "map": {"gameplay": {"roles": {"startNodeId": "S01", "gateNodeId": "S14", "terminalNodeIds": ["S15"]}}},
            "nodes": [
                {"nodeId": "S01", "start": True},
                {"nodeId": "S02", "processType": "TRANSFER", "processRound": 4},
                {"nodeId": "S04"},
                {"nodeId": "S14", "processRound": 6},
                {"nodeId": "S15", "terminal": True},
            ],
            "edges": [
                {"edgeId": "E1", "fromNodeId": "S02", "toNodeId": "S04", "routeType": "ROAD", "distance": 20},
                {"edgeId": "E2", "fromNodeId": "S04", "toNodeId": "S14", "routeType": "ROAD", "distance": 1},
                {"edgeId": "E3", "fromNodeId": "S14", "toNodeId": "S15", "routeType": "ROAD", "distance": 1},
            ],
        }
        memory = GameMemory(1001)
        context = memory.apply_start(start)
        engine = DecisionEngine(memory)
        tasks = [{"taskId": "T08_008", "nodeId": "S04", "score": 30, "processRound": 4, "active": True}]
        snap = snapshot(
            memory,
            currentNodeId="S02",
            taskScore=0,
            nodes=start["nodes"],
            tasks=tasks,
            opponent_overrides={"playerId": 2002, "currentNodeId": "S02", "state": "IDLE"},
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "PROCESS", "targetNodeId": "S02"}])
        self.assertIn("process node S02", engine.last_reason)

    def test_competes_for_fixed_process_before_base_task_score_against_busy_opponent(self):
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
            taskScore=0,
            nodes=nodes,
            opponent_overrides={"playerId": 2002, "currentNodeId": "S02", "state": "PROCESSING"},
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "PROCESS", "targetNodeId": "S02"}])
        self.assertIn("process node S02", engine.last_reason)

    def test_claims_current_task_before_process_against_idle_opponent(self):
        memory, context, engine = self.make_engine()
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S02", "processType": "TRANSFER", "processRound": 4},
            {"nodeId": "S14"},
            {"nodeId": "S15", "terminal": True},
        ]
        tasks = [{"taskId": "T12_012", "nodeId": "S02", "score": 15, "active": True}]
        snap = snapshot(
            memory,
            currentNodeId="S02",
            taskScore=0,
            nodes=nodes,
            tasks=tasks,
            opponent_overrides={"playerId": 2002, "currentNodeId": "S02", "state": "IDLE"},
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "CLAIM_TASK", "taskId": "T12_012"}])
        self.assertIn("before process S02", engine.last_reason)

    def test_claims_current_task_before_process_against_busy_opponent(self):
        memory, context, engine = self.make_engine()
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S02", "processType": "TRANSFER", "processRound": 4},
            {"nodeId": "S14"},
            {"nodeId": "S15", "terminal": True},
        ]
        tasks = [{"taskId": "T12_012", "nodeId": "S02", "score": 15, "active": True}]
        snap = snapshot(
            memory,
            currentNodeId="S02",
            taskScore=90,
            nodes=nodes,
            tasks=tasks,
            opponent_overrides={"playerId": 2002, "currentNodeId": "S02", "state": "PROCESSING"},
        )
        self.assertEqual(engine.decide(context, snap), [{"action": "CLAIM_TASK", "taskId": "T12_012"}])
        self.assertIn("before process S02", engine.last_reason)

    def test_claims_task_before_process_after_stretch_task_score(self):
        memory, context, engine = self.make_engine()
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S02", "processType": "TRANSFER", "processRound": 4},
            {"nodeId": "S14"},
            {"nodeId": "S15", "terminal": True},
        ]
        tasks = [
            {"taskId": "T_DONE_1", "nodeId": "S01", "score": 30, "completed": True, "ownerPlayerId": 1001},
            {"taskId": "T_DONE_2", "nodeId": "S01", "score": 30, "completed": True, "ownerPlayerId": 1001},
            {"taskId": "T_DONE_3", "nodeId": "S01", "score": 30, "completed": True, "ownerPlayerId": 1001},
            {"taskId": "T_DONE_4", "nodeId": "S01", "score": 15, "completed": True, "ownerPlayerId": 1001},
            {"taskId": "T12_012", "nodeId": "S02", "score": 15, "active": True},
        ]
        snap = snapshot(
            memory,
            currentNodeId="S02",
            nodes=nodes,
            tasks=tasks,
            opponent_overrides={"playerId": 2002, "currentNodeId": "S02", "state": "PROCESSING"},
        )
        self.assertEqual(engine.decide(context, snap), [{"action": "CLAIM_TASK", "taskId": "T12_012"}])
        self.assertIn("before process S02", engine.last_reason)

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

    def test_drawn_fixed_process_contest_yields_before_retry(self):
        memory, context, engine = self.make_engine()
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S02", "processType": "TRANSFER", "processRound": 4},
            {"nodeId": "S14"},
            {"nodeId": "S15", "terminal": True},
        ]
        contest_start = {
            "type": "WINDOW_CONTEST_START",
            "payload": {"contestId": "C1", "objectKey": "PROCESS:S02:TRANSFER", "targetNodeId": "S02"},
        }
        contest_end = {
            "type": "WINDOW_CONTEST_END",
            "payload": {"contestId": "C1", "winnerTeamId": "DRAW"},
        }
        rest_complete = {
            "type": "PROCESS_COMPLETE",
            "payload": {"playerId": 1001, "targetNodeId": "S02", "action": "REST", "objectKey": "REST:C1:RED"},
        }

        snapshot(memory, state="CONTESTING", currentNodeId="S02", nodes=nodes, events=[contest_start], round_no=44)
        snapshot(memory, state="RESTING", currentNodeId="S02", nodes=nodes, events=[contest_end], round_no=47)
        snap = snapshot(
            memory,
            currentNodeId="S02",
            nodes=nodes,
            events=[rest_complete],
            opponent_overrides={"currentNodeId": "S02", "state": "IDLE"},
            round_no=49,
        )

        self.assertIn("S02", memory.skipped_process_nodes)
        self.assertNotIn("S02", memory.completed_process_nodes)
        self.assertEqual(engine.decide(context, snap), [])
        self.assertIn("yield drawn process node S02", engine.last_reason)

        retry = snapshot(
            memory,
            currentNodeId="S02",
            nodes=nodes,
            opponent_overrides={"currentNodeId": "S02", "state": "PROCESSING"},
            round_no=50,
        )
        self.assertEqual(engine.decide(context, retry), [{"action": "PROCESS", "targetNodeId": "S02"}])
        self.assertNotIn("S02", memory.skipped_process_nodes)

    def test_drawn_fixed_process_retries_before_yield_when_downstream_task_pressure(self):
        start = {
            "matchId": "m1",
            "round": 1,
            "durationRound": 600,
            "players": [{"playerId": 1001, "teamId": "RED"}, {"playerId": 2002, "teamId": "BLUE"}],
            "map": {"gameplay": {"roles": {"startNodeId": "S01", "gateNodeId": "S14", "terminalNodeIds": ["S15"]}}},
            "nodes": [
                {"nodeId": "S01", "start": True},
                {"nodeId": "S02", "processType": "TRANSFER", "processRound": 4},
                {"nodeId": "S04"},
                {"nodeId": "S14", "processRound": 6},
                {"nodeId": "S15", "terminal": True},
            ],
            "edges": [
                {"edgeId": "E1", "fromNodeId": "S02", "toNodeId": "S04", "routeType": "ROAD", "distance": 20},
                {"edgeId": "E2", "fromNodeId": "S04", "toNodeId": "S14", "routeType": "ROAD", "distance": 1},
                {"edgeId": "E3", "fromNodeId": "S14", "toNodeId": "S15", "routeType": "ROAD", "distance": 1},
            ],
        }
        memory = GameMemory(1001)
        context = memory.apply_start(start)
        engine = DecisionEngine(memory)
        tasks = [{"taskId": "T08_008", "nodeId": "S04", "score": 30, "processRound": 4, "active": True}]
        contest_start = {
            "type": "WINDOW_CONTEST_START",
            "payload": {"contestId": "C1", "objectKey": "PROCESS:S02:TRANSFER", "targetNodeId": "S02"},
        }
        contest_end = {
            "type": "WINDOW_CONTEST_END",
            "payload": {"contestId": "C1", "winnerTeamId": "DRAW"},
        }
        rest_complete = {
            "type": "PROCESS_COMPLETE",
            "payload": {"playerId": 1001, "targetNodeId": "S02", "action": "REST", "objectKey": "REST:C1:RED"},
        }

        snapshot(memory, state="CONTESTING", currentNodeId="S02", nodes=start["nodes"], tasks=tasks, events=[contest_start])
        snapshot(memory, state="RESTING", currentNodeId="S02", nodes=start["nodes"], tasks=tasks, events=[contest_end])
        snap = snapshot(
            memory,
            currentNodeId="S02",
            nodes=start["nodes"],
            tasks=tasks,
            events=[rest_complete],
            opponent_overrides={"currentNodeId": "S02", "state": "IDLE"},
            round_no=49,
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "PROCESS", "targetNodeId": "S02"}])
        self.assertEqual(memory.drawn_process_retry_counts["S02"], 1)
        self.assertNotIn("S02", memory.skipped_process_nodes)

    def test_drawn_fixed_process_yields_after_pressure_retry_limit(self):
        memory, context, engine = self.make_engine()
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S02", "processType": "TRANSFER", "processRound": 4},
            {"nodeId": "S04"},
            {"nodeId": "S14"},
            {"nodeId": "S15", "terminal": True},
        ]
        tasks = [{"taskId": "T08_008", "nodeId": "S04", "score": 30, "processRound": 4, "active": True}]
        memory.skipped_process_nodes.add("S02")
        memory.drawn_process_retry_counts["S02"] = 1

        snap = snapshot(
            memory,
            currentNodeId="S02",
            nodes=nodes,
            tasks=tasks,
            opponent_overrides={"currentNodeId": "S02", "state": "IDLE"},
            round_no=56,
        )

        self.assertEqual(engine.decide(context, snap), [])
        self.assertIn("yield drawn process node S02", engine.last_reason)

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

    def test_reentered_fixed_process_node_requires_new_process(self):
        memory, context, engine = self.make_engine()
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S13", "processType": "PALACE_TRANSFER", "processRound": 5},
            {"nodeId": "S14"},
            {"nodeId": "S15", "terminal": True},
        ]
        process_complete = {
            "type": "PROCESS_COMPLETE",
            "payload": {
                "playerId": 1001,
                "targetNodeId": "S13",
                "action": "PROCESS",
                "objectKey": "PROCESS:S13:PALACE_TRANSFER",
            },
        }
        snapshot(memory, currentNodeId="S13", nodes=nodes, events=[process_complete])
        self.assertIn("S13", memory.completed_process_nodes)

        node_enter = {
            "type": "NODE_ENTER",
            "payload": {"playerId": 1001, "fromNodeId": "S12", "nodeId": "S13"},
        }
        snap = snapshot(
            memory,
            phase="RUSH",
            currentNodeId="S13",
            taskScore=80,
            nodes=nodes,
            events=[node_enter],
            round_no=474,
            opponent_overrides={"delivered": True, "state": "DELIVERED", "currentNodeId": "S15"},
        )

        self.assertNotIn("S13", memory.completed_process_nodes)
        self.assertEqual(engine.decide(context, snap), [{"action": "PROCESS", "targetNodeId": "S13"}])
        self.assertNotEqual(engine.last_reason, "move from S13 to S14 toward S14")

    def test_process_required_rejection_retries_process(self):
        memory, context, engine = self.make_engine()
        memory.completed_process_nodes.add("S02")
        memory.skipped_process_nodes.add("S02")
        memory.drawn_process_yield_counts["S02"] = 1
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
        self.assertNotIn("S02", memory.skipped_process_nodes)
        self.assertNotIn("S02", memory.drawn_process_yield_counts)
        self.assertEqual(engine.decide(context, snap), [{"action": "PROCESS", "targetNodeId": "S02"}])

    def test_drawn_resource_contest_skips_same_resource(self):
        memory, context, engine = self.make_engine()
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S02", "resourceStock": {"INTEL": 1}},
            {"nodeId": "S14"},
            {"nodeId": "S15", "terminal": True},
        ]
        contest_start = {
            "type": "WINDOW_CONTEST_START",
            "payload": {
                "contestId": "C1",
                "objectKey": "RESOURCE:S02:INTEL",
                "targetNodeId": "S02",
                "resourceType": "INTEL",
            },
        }
        contest_end = {
            "type": "WINDOW_CONTEST_END",
            "payload": {"contestId": "C1", "winnerTeamId": "DRAW"},
        }

        snapshot(memory, state="RESTING", currentNodeId="S02", nodes=nodes, events=[contest_start, contest_end])
        snap = snapshot(memory, currentNodeId="S02", taskScore=90, nodes=nodes)

        self.assertIn("RESOURCE:S02:INTEL", memory.skipped_resource_claims)
        self.assertEqual(engine.decide(context, snap), [{"action": "MOVE", "targetNodeId": "S14"}])
        self.assertNotEqual(engine.last_reason, "claim resource INTEL at S02")

    def test_drawn_resource_contest_allows_other_resource(self):
        memory, context, engine = self.make_engine()
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S02", "resourceStock": {"INTEL": 1, "PASS_TOKEN": 1}},
            {"nodeId": "S14"},
            {"nodeId": "S15", "terminal": True},
        ]
        memory.skipped_resource_claims.add("RESOURCE:S02:INTEL")

        snap = snapshot(memory, currentNodeId="S02", taskScore=60, nodes=nodes)

        self.assertEqual(
            engine.decide(context, snap),
            [{"action": "CLAIM_RESOURCE", "targetNodeId": "S02", "resourceType": "PASS_TOKEN"}],
        )
        self.assertIn("claim resource PASS_TOKEN", engine.last_reason)

    def test_drawn_task_contest_skips_same_task_for_same_node_opponent(self):
        memory, context, engine = self.make_engine()
        tasks = [
            {"taskId": "T02_003", "nodeId": "S02", "score": 30, "active": True},
            {"taskId": "T11_011", "nodeId": "S02", "score": 30, "active": True},
        ]
        contest_start = {
            "type": "WINDOW_CONTEST_START",
            "payload": {
                "contestId": "C1",
                "contestType": "TASK",
                "targetNodeId": "S02",
                "taskId": "T02_003",
                "objectKey": "TASK:T02_003",
            },
        }
        contest_end = {
            "type": "WINDOW_CONTEST_END",
            "payload": {"contestId": "C1", "winnerTeamId": "DRAW"},
        }

        snapshot(memory, state="CONTESTING", currentNodeId="S02", tasks=tasks, events=[contest_start])
        snapshot(memory, state="RESTING", currentNodeId="S02", tasks=tasks, events=[contest_end])
        snap = snapshot(
            memory,
            currentNodeId="S02",
            tasks=tasks,
            opponent_overrides={"currentNodeId": "S02", "state": "IDLE"},
        )

        self.assertIn("T02_003", memory.skipped_task_claims)
        self.assertNotIn("S02", memory.skipped_process_nodes)
        self.assertEqual(engine.decide(context, snap), [{"action": "CLAIM_TASK", "taskId": "T11_011"}])
        self.assertNotEqual(engine.last_reason, "claim current task T02_003")

    def test_drawn_task_contest_moves_on_when_no_alternate_current_task(self):
        memory, context, engine = self.make_engine()
        tasks = [{"taskId": "T02_003", "nodeId": "S02", "score": 30, "active": True}]
        memory.skipped_task_claims.add("T02_003")

        snap = snapshot(
            memory,
            currentNodeId="S02",
            tasks=tasks,
            opponent_overrides={"currentNodeId": "S02", "state": "IDLE"},
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "MOVE", "targetNodeId": "S14"}])
        self.assertIn("move from S02 to S14", engine.last_reason)

    def test_drawn_task_contest_allows_retry_after_opponent_leaves(self):
        memory, context, engine = self.make_engine()
        tasks = [{"taskId": "T02_003", "nodeId": "S02", "score": 30, "active": True}]
        memory.skipped_task_claims.add("T02_003")

        snap = snapshot(
            memory,
            currentNodeId="S02",
            tasks=tasks,
            opponent_overrides={"currentNodeId": "S02", "state": "MOVING", "nextNodeId": "S14"},
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "CLAIM_TASK", "taskId": "T02_003"}])
        self.assertNotIn("T02_003", memory.skipped_task_claims)

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

    def test_claims_optional_resource_before_base_task_score(self):
        memory, context, engine = self.make_engine()
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S02", "resourceStock": {"INTEL": 1}},
            {"nodeId": "S14"},
            {"nodeId": "S15", "terminal": True},
        ]

        self.assertEqual(
            engine.decide(context, snapshot(memory, currentNodeId="S02", taskScore=60, nodes=nodes)),
            [{"action": "CLAIM_RESOURCE", "targetNodeId": "S02", "resourceType": "INTEL"}],
        )

    def test_skips_low_yield_resource_when_reachable_task_remains_before_base_score(self):
        start = {
            "matchId": "m1",
            "round": 1,
            "durationRound": 600,
            "players": [{"playerId": 1001, "teamId": "RED"}, {"playerId": 2002, "teamId": "BLUE"}],
            "map": {"gameplay": {"roles": {"startNodeId": "S01", "gateNodeId": "S14", "terminalNodeIds": ["S15"]}}},
            "nodes": [
                {"nodeId": "S01", "start": True},
                {"nodeId": "S02", "resourceStock": {"INTEL": 1}},
                {"nodeId": "S03"},
                {"nodeId": "S14", "processRound": 6},
                {"nodeId": "S15", "terminal": True},
            ],
            "edges": [
                {"edgeId": "E1", "fromNodeId": "S02", "toNodeId": "S03", "routeType": "ROAD", "distance": 1},
                {"edgeId": "E2", "fromNodeId": "S03", "toNodeId": "S14", "routeType": "ROAD", "distance": 1},
                {"edgeId": "E3", "fromNodeId": "S14", "toNodeId": "S15", "routeType": "ROAD", "distance": 1},
            ],
        }
        memory = GameMemory(1001)
        context = memory.apply_start(start)
        engine = DecisionEngine(memory)
        tasks = [{"taskId": "T02_002", "nodeId": "S03", "score": 30, "processRound": 4, "active": True}]

        self.assertEqual(
            engine.decide(context, snapshot(memory, currentNodeId="S02", taskScore=60, nodes=start["nodes"], tasks=tasks)),
            [{"action": "MOVE", "targetNodeId": "S03"}],
        )

    def test_skips_optional_resource_after_base_task_score(self):
        memory, context, engine = self.make_engine()
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S02", "resourceStock": {"INTEL": 1}},
            {"nodeId": "S14"},
            {"nodeId": "S15", "terminal": True},
        ]
        tasks = [
            {"taskId": "T_DONE_1", "nodeId": "S01", "score": 30, "completed": True, "ownerPlayerId": 1001},
            {"taskId": "T_DONE_2", "nodeId": "S01", "score": 30, "completed": True, "ownerPlayerId": 1001},
            {"taskId": "T_DONE_3", "nodeId": "S01", "score": 30, "completed": True, "ownerPlayerId": 1001},
        ]

        self.assertEqual(
            engine.decide(context, snapshot(memory, currentNodeId="S02", nodes=nodes, tasks=tasks)),
            [{"action": "MOVE", "targetNodeId": "S14"}],
        )

    def test_claims_ice_box_after_base_task_score(self):
        memory, context, engine = self.make_engine()
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S02", "resourceStock": {"ICE_BOX": 1}},
            {"nodeId": "S14"},
            {"nodeId": "S15", "terminal": True},
        ]
        tasks = [
            {"taskId": "T_DONE_1", "nodeId": "S01", "score": 30, "completed": True, "ownerPlayerId": 1001},
            {"taskId": "T_DONE_2", "nodeId": "S01", "score": 30, "completed": True, "ownerPlayerId": 1001},
            {"taskId": "T_DONE_3", "nodeId": "S01", "score": 30, "completed": True, "ownerPlayerId": 1001},
        ]

        self.assertEqual(
            engine.decide(context, snapshot(memory, currentNodeId="S02", nodes=nodes, tasks=tasks)),
            [{"action": "CLAIM_RESOURCE", "targetNodeId": "S02", "resourceType": "ICE_BOX"}],
        )

    def test_late_endgame_skips_current_resource(self):
        memory, context, engine = self.make_engine()
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S02", "resourceStock": {"FAST_HORSE": 1}},
            {"nodeId": "S14"},
            {"nodeId": "S15", "terminal": True},
        ]
        snap = snapshot(memory, currentNodeId="S02", taskScore=30, nodes=nodes, round_no=430)
        self.assertEqual(engine.decide(context, snap), [{"action": "MOVE", "targetNodeId": "S14"}])

    def test_late_remote_task_without_delivery_budget_goes_endgame(self):
        start = {
            "matchId": "m1",
            "round": 1,
            "durationRound": 600,
            "players": [{"playerId": 1001, "teamId": "RED"}, {"playerId": 2002, "teamId": "BLUE"}],
            "map": {"gameplay": {"roles": {"startNodeId": "S01", "gateNodeId": "S14", "terminalNodeIds": ["S15"]}}},
            "nodes": [
                {"nodeId": "S01", "start": True},
                {"nodeId": "S07"},
                {"nodeId": "S12"},
                {"nodeId": "S13"},
                {"nodeId": "S14", "processRound": 6},
                {"nodeId": "S15", "terminal": True},
            ],
            "edges": [
                {"edgeId": "E1", "fromNodeId": "S13", "toNodeId": "S12", "routeType": "ROAD", "distance": 25},
                {"edgeId": "E2", "fromNodeId": "S12", "toNodeId": "S07", "routeType": "ROAD", "distance": 300},
                {"edgeId": "E3", "fromNodeId": "S13", "toNodeId": "S14", "routeType": "ROAD", "distance": 18},
                {"edgeId": "E4", "fromNodeId": "S14", "toNodeId": "S15", "routeType": "ROAD", "distance": 10},
            ],
        }
        memory = GameMemory(1001)
        context = memory.apply_start(start)
        engine = DecisionEngine(memory)
        tasks = [{"taskId": "T02_002", "nodeId": "S07", "score": 30, "processRound": 4, "active": True}]
        snap = snapshot(memory, currentNodeId="S13", taskScore=75, nodes=start["nodes"], tasks=tasks, round_no=409)

        self.assertEqual(engine.decide(context, snap), [{"action": "MOVE", "targetNodeId": "S14"}])
        self.assertIn("toward S14", engine.last_reason)

    def test_early_remote_task_with_delivery_budget_is_still_selected(self):
        start = {
            "matchId": "m1",
            "round": 1,
            "durationRound": 600,
            "players": [{"playerId": 1001, "teamId": "RED"}, {"playerId": 2002, "teamId": "BLUE"}],
            "map": {"gameplay": {"roles": {"startNodeId": "S01", "gateNodeId": "S14", "terminalNodeIds": ["S15"]}}},
            "nodes": [
                {"nodeId": "S01", "start": True},
                {"nodeId": "S07"},
                {"nodeId": "S12"},
                {"nodeId": "S13"},
                {"nodeId": "S14", "processRound": 6},
                {"nodeId": "S15", "terminal": True},
            ],
            "edges": [
                {"edgeId": "E1", "fromNodeId": "S13", "toNodeId": "S12", "routeType": "ROAD", "distance": 1},
                {"edgeId": "E2", "fromNodeId": "S12", "toNodeId": "S07", "routeType": "ROAD", "distance": 1},
                {"edgeId": "E3", "fromNodeId": "S13", "toNodeId": "S14", "routeType": "ROAD", "distance": 18},
                {"edgeId": "E4", "fromNodeId": "S14", "toNodeId": "S15", "routeType": "ROAD", "distance": 10},
            ],
        }
        memory = GameMemory(1001)
        context = memory.apply_start(start)
        engine = DecisionEngine(memory)
        tasks = [{"taskId": "T02_002", "nodeId": "S07", "score": 30, "processRound": 4, "active": True}]
        snap = snapshot(memory, currentNodeId="S13", taskScore=30, nodes=start["nodes"], tasks=tasks, round_no=10)

        self.assertEqual(engine.decide(context, snap), [{"action": "MOVE", "targetNodeId": "S12"}])
        self.assertIn("toward S07", engine.last_reason)

    def test_endgame_claims_safe_current_task_before_moving(self):
        memory, context, engine = self.make_engine()
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S13"},
            {"nodeId": "S14", "processRound": 6},
            {"nodeId": "S15", "terminal": True},
        ]
        tasks = [{"taskId": "T13_013", "nodeId": "S13", "score": 15, "processRound": 5, "active": True}]
        snap = snapshot(memory, currentNodeId="S13", taskScore=75, nodes=nodes, tasks=tasks, round_no=560)
        self.assertEqual(engine.decide(context, snap), [{"action": "CLAIM_TASK", "taskId": "T13_013"}])

    def test_endgame_claims_safe_current_task_after_base_threshold(self):
        memory, context, engine = self.make_engine()
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S13"},
            {"nodeId": "S14", "processRound": 6},
            {"nodeId": "S15", "terminal": True},
        ]
        tasks = [{"taskId": "T13_013", "nodeId": "S13", "score": 15, "processRound": 5, "active": True}]
        snap = snapshot(memory, currentNodeId="S13", taskScore=120, nodes=nodes, tasks=tasks, round_no=560)
        self.assertEqual(engine.decide(context, snap), [{"action": "CLAIM_TASK", "taskId": "T13_013"}])

    def test_endgame_above_threshold_skips_current_task_when_delivery_budget_is_too_small(self):
        memory, context, engine = self.make_engine()
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S13"},
            {"nodeId": "S14", "processRound": 6},
            {"nodeId": "S15", "terminal": True},
        ]
        tasks = [{"taskId": "T13_013", "nodeId": "S13", "score": 15, "processRound": 5, "active": True}]
        snap = snapshot(memory, currentNodeId="S13", taskScore=120, nodes=nodes, tasks=tasks, round_no=580)
        self.assertEqual(engine.decide(context, snap), [{"action": "MOVE", "targetNodeId": "S14"}])

    def test_endgame_skips_current_task_when_delivery_budget_is_too_small(self):
        memory, context, engine = self.make_engine()
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S13"},
            {"nodeId": "S14", "processRound": 6},
            {"nodeId": "S15", "terminal": True},
        ]
        tasks = [{"taskId": "T13_013", "nodeId": "S13", "score": 15, "processRound": 5, "active": True}]
        snap = snapshot(memory, currentNodeId="S13", taskScore=75, nodes=nodes, tasks=tasks, round_no=590)
        self.assertEqual(engine.decide(context, snap), [{"action": "MOVE", "targetNodeId": "S14"}])

    def test_endgame_current_task_does_not_start_required_resource_chain(self):
        memory, context, engine = self.make_engine()
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S13", "resourceStock": {"FAST_HORSE": 1}},
            {"nodeId": "S14", "processRound": 6},
            {"nodeId": "S15", "terminal": True},
        ]
        tasks = [
            {
                "taskId": "T06_013",
                "nodeId": "S13",
                "score": 30,
                "processRound": 3,
                "requiredResourceTypes": ["FAST_HORSE"],
                "active": True,
            }
        ]
        snap = snapshot(memory, currentNodeId="S13", taskScore=60, nodes=nodes, tasks=tasks, round_no=560)
        self.assertEqual(engine.decide(context, snap), [{"action": "MOVE", "targetNodeId": "S14"}])

    def test_skips_resource_opponent_is_processing_same_resource(self):
        memory, context, engine = self.make_engine()
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S02", "resourceStock": {"ICE_BOX": 1}},
            {"nodeId": "S14"},
            {"nodeId": "S15", "terminal": True},
        ]
        snap = snapshot(
            memory,
            currentNodeId="S02",
            taskScore=90,
            nodes=nodes,
            opponent_overrides={
                "currentNodeId": "S02",
                "state": "PROCESSING",
                "currentProcess": {"action": "CLAIM_RESOURCE", "resourceType": "ICE_BOX"},
            },
        )
        self.assertEqual(engine.decide(context, snap), [{"action": "MOVE", "targetNodeId": "S14"}])

    def test_skips_low_value_same_node_resource_contest(self):
        memory, context, engine = self.make_engine()
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S02", "resourceStock": {"OFFICIAL_PERMIT": 1}},
            {"nodeId": "S14"},
            {"nodeId": "S15", "terminal": True},
        ]
        snap = snapshot(
            memory,
            currentNodeId="S02",
            taskScore=90,
            nodes=nodes,
            opponent_overrides={"currentNodeId": "S02", "state": "IDLE"},
        )
        self.assertEqual(engine.decide(context, snap), [{"action": "MOVE", "targetNodeId": "S14"}])

    def test_contesting_state_only_sends_task_window_card(self):
        memory, context, engine = self.make_engine()
        contests = [{"contestId": "C1", "contestType": "TASK", "redPlayerId": 1001, "bluePlayerId": 2002, "roundIndex": 1}]
        snap = snapshot(memory, state="CONTESTING", currentNodeId="S02", contests=contests)
        self.assertEqual(engine.decide(context, snap), [{"action": "WINDOW_CARD", "contestId": "C1", "card": "XIAN_GONG"}])

    def test_task_window_falls_back_to_bing_zheng_when_xian_gong_is_not_safe(self):
        memory, context, engine = self.make_engine()
        contests = [{"contestId": "C1", "contestType": "TASK", "redPlayerId": 1001, "bluePlayerId": 2002, "roundIndex": 1}]
        snap = snapshot(
            memory,
            state="CONTESTING",
            currentNodeId="S02",
            freshness=70,
            goodFruit=30,
            contests=contests,
        )
        self.assertEqual(engine.decide(context, snap), [{"action": "WINDOW_CARD", "contestId": "C1", "card": "BING_ZHENG"}])

    def test_task_window_preserves_only_horse_resource_for_t06(self):
        memory, context, engine = self.make_engine()
        contests = [
            {
                "contestId": "C1",
                "contestType": "TASK",
                "taskId": "T06_006",
                "redPlayerId": 1001,
                "bluePlayerId": 2002,
                "roundIndex": 2,
            }
        ]
        tasks = [
            {
                "taskId": "T06_006",
                "taskTemplateId": "T06",
                "nodeId": "S09",
                "processType": "HORSE_TRANSFER",
                "score": 30,
                "active": True,
            }
        ]
        snap = snapshot(
            memory,
            state="CONTESTING",
            currentNodeId="S09",
            guardActionPoint=4,
            resources={"FAST_HORSE": 1},
            tasks=tasks,
            contests=contests,
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "WINDOW_CARD", "contestId": "C1", "card": "XIAN_GONG"}])

    def test_task_window_abstains_before_spending_only_horse_when_no_safe_card_exists(self):
        memory, context, engine = self.make_engine()
        contests = [
            {
                "contestId": "C1",
                "contestType": "TASK",
                "taskId": "T06_006",
                "redPlayerId": 1001,
                "bluePlayerId": 2002,
            }
        ]
        tasks = [
            {
                "taskId": "T06_006",
                "taskTemplateId": "T06",
                "nodeId": "S09",
                "processType": "HORSE_TRANSFER",
                "score": 30,
                "active": True,
            }
        ]
        snap = snapshot(
            memory,
            state="CONTESTING",
            currentNodeId="S09",
            freshness=70,
            goodFruit=30,
            guardActionPoint=0,
            resources={"FAST_HORSE": 1},
            tasks=tasks,
            contests=contests,
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "WINDOW_CARD", "contestId": "C1", "card": "ABSTAIN"}])

    def test_task_window_allows_qiang_xing_when_horse_buff_makes_it_free(self):
        memory, context, engine = self.make_engine()
        contests = [
            {
                "contestId": "C1",
                "contestType": "TASK",
                "taskId": "T06_006",
                "redPlayerId": 1001,
                "bluePlayerId": 2002,
            }
        ]
        tasks = [
            {
                "taskId": "T06_006",
                "taskTemplateId": "T06",
                "nodeId": "S09",
                "processType": "HORSE_TRANSFER",
                "score": 30,
                "active": True,
            }
        ]
        snap = snapshot(
            memory,
            state="CONTESTING",
            currentNodeId="S09",
            guardActionPoint=0,
            resources={"FAST_HORSE": 1},
            buffs=[{"type": "FAST_HORSE"}],
            tasks=tasks,
            contests=contests,
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "WINDOW_CARD", "contestId": "C1", "card": "QIANG_XING"}])

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
