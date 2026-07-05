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
        {"nodeId": "S13"},
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
        {"edgeId": "E9", "fromNodeId": "S12", "toNodeId": "S13", "routeType": "ROAD", "distance": 1},
        {"edgeId": "E10", "fromNodeId": "S13", "toNodeId": "S14", "routeType": "ROAD", "distance": 1},
    ],
    "taskTemplates": [
        {
            "taskTemplateId": "T06",
            "requiredResourceTypes": ["FAST_HORSE"],
        }
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

    def make_delivery_map_engine(self):
        start = {
            "matchId": "delivery-risk",
            "round": 1,
            "durationRound": 600,
            "players": [{"playerId": 1001, "teamId": "RED"}, {"playerId": 2002, "teamId": "BLUE"}],
            "map": {"gameplay": {"roles": {"startNodeId": "S01", "gateNodeId": "S14", "terminalNodeIds": ["S15"]}}},
            "nodes": [
                {"nodeId": "S01", "start": True},
                {"nodeId": "S04", "processType": "BOARD", "processRound": 7},
                {"nodeId": "S05", "processType": "WATER_TRANSFER", "processRound": 6},
                {"nodeId": "S07"},
                {"nodeId": "S09"},
                {"nodeId": "S10"},
                {"nodeId": "S11", "processType": "PASS_TRANSFER", "processRound": 5},
                {"nodeId": "S12"},
                {"nodeId": "S13", "processType": "PALACE_TRANSFER", "processRound": 5},
                {"nodeId": "S14", "processType": "VERIFY", "processRound": 6},
                {"nodeId": "S15", "terminal": True},
            ],
            "edges": [
                {"edgeId": "E21", "fromNodeId": "S07", "toNodeId": "S04", "routeType": "BRANCH", "distance": 54},
                {"edgeId": "E13", "fromNodeId": "S07", "toNodeId": "S05", "routeType": "BRANCH", "distance": 46},
                {"edgeId": "E19", "fromNodeId": "S05", "toNodeId": "S09", "routeType": "WATER", "distance": 48},
                {"edgeId": "E04", "fromNodeId": "S07", "toNodeId": "S09", "routeType": "ROAD", "distance": 46},
                {"edgeId": "E05", "fromNodeId": "S09", "toNodeId": "S10", "routeType": "ROAD", "distance": 40},
                {"edgeId": "E06", "fromNodeId": "S10", "toNodeId": "S11", "routeType": "ROAD", "distance": 36},
                {"edgeId": "E07", "fromNodeId": "S11", "toNodeId": "S12", "routeType": "ROAD", "distance": 20},
                {"edgeId": "E08", "fromNodeId": "S12", "toNodeId": "S13", "routeType": "ROAD", "distance": 25},
                {"edgeId": "E09", "fromNodeId": "S13", "toNodeId": "S14", "routeType": "ROAD", "distance": 18},
                {"edgeId": "E10", "fromNodeId": "S14", "toNodeId": "S15", "routeType": "ROAD", "distance": 10},
            ],
        }
        memory = GameMemory(1001)
        context = memory.apply_start(start)
        return memory, context, DecisionEngine(memory), start["nodes"]

    def make_replay_split_engine(self):
        start = {
            "matchId": "replay-split",
            "round": 1,
            "durationRound": 600,
            "players": [{"playerId": 1001, "teamId": "RED"}, {"playerId": 1002, "teamId": "BLUE"}],
            "map": {"gameplay": {"roles": {"startNodeId": "S01", "gateNodeId": "S14", "terminalNodeIds": ["S15"]}}},
            "nodes": [
                {"nodeId": "S01", "start": True},
                {"nodeId": "S02", "processType": "TRANSFER", "processRound": 4},
                {"nodeId": "S03"},
                {"nodeId": "S04", "processType": "BOARD", "processRound": 7, "resourceStock": {"SHORT_HORSE": 1}},
                {"nodeId": "S05", "processType": "WATER_TRANSFER", "processRound": 6},
                {"nodeId": "S07"},
                {"nodeId": "S09"},
                {"nodeId": "S10"},
                {"nodeId": "S11"},
                {"nodeId": "S12"},
                {"nodeId": "S13"},
                {"nodeId": "S14", "processType": "VERIFY", "processRound": 6},
                {"nodeId": "S15", "terminal": True},
            ],
            "edges": [
                {"edgeId": "E02", "fromNodeId": "S02", "toNodeId": "S03", "routeType": "ROAD", "distance": 25},
                {"edgeId": "E11", "fromNodeId": "S02", "toNodeId": "S04", "routeType": "ROAD", "distance": 20},
                {"edgeId": "E03", "fromNodeId": "S03", "toNodeId": "S07", "routeType": "ROAD", "distance": 54},
                {"edgeId": "E12", "fromNodeId": "S04", "toNodeId": "S05", "routeType": "WATER", "distance": 44},
                {"edgeId": "E19", "fromNodeId": "S05", "toNodeId": "S09", "routeType": "WATER", "distance": 48},
                {"edgeId": "E04", "fromNodeId": "S07", "toNodeId": "S09", "routeType": "ROAD", "distance": 46},
                {"edgeId": "E05", "fromNodeId": "S09", "toNodeId": "S10", "routeType": "ROAD", "distance": 40},
                {"edgeId": "E06", "fromNodeId": "S10", "toNodeId": "S11", "routeType": "ROAD", "distance": 36},
                {"edgeId": "E07", "fromNodeId": "S11", "toNodeId": "S12", "routeType": "ROAD", "distance": 20},
                {"edgeId": "E08", "fromNodeId": "S12", "toNodeId": "S13", "routeType": "ROAD", "distance": 25},
                {"edgeId": "E09", "fromNodeId": "S13", "toNodeId": "S14", "routeType": "ROAD", "distance": 18},
                {"edgeId": "E10", "fromNodeId": "S14", "toNodeId": "S15", "routeType": "ROAD", "distance": 10},
            ],
            "taskTemplates": [
                {
                    "taskTemplateId": "T06",
                    "processType": "HORSE_TRANSFER",
                    "requiredResourceTypes": ["FAST_HORSE"],
                }
            ],
        }
        memory = GameMemory(1002)
        context = memory.apply_start(start)
        memory.completed_process_nodes.add("S02")
        return memory, context, DecisionEngine(memory), start["nodes"]

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

    def test_uses_fast_horse_while_moving_with_long_travel_ahead(self):
        memory, context, engine = self.make_engine()
        snap = snapshot(
            memory,
            state="MOVING",
            currentNodeId="S09",
            nextNodeId="S10",
            edgeProgressMs=1000,
            edgeTotalMs=20000,
            resources={"FAST_HORSE": 1},
            taskScore=60,
            tasks=[{"taskId": "T02_1", "nodeId": "S10", "score": 30, "active": True}],
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "USE_RESOURCE", "resourceType": "FAST_HORSE"}])
        self.assertIn("use FAST_HORSE", engine.last_reason)

    def test_does_not_use_horse_when_speed_buff_is_active(self):
        memory, context, engine = self.make_engine()
        snap = snapshot(
            memory,
            state="MOVING",
            currentNodeId="S09",
            nextNodeId="S10",
            edgeProgressMs=1000,
            edgeTotalMs=20000,
            resources={"FAST_HORSE": 1},
            buffs=[{"type": "RUSH_SPEED"}],
            taskScore=60,
            tasks=[{"taskId": "T02_1", "nodeId": "S10", "score": 30, "active": True}],
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "MOVE", "targetNodeId": "S10"}])

    def test_does_not_spend_horse_en_route_to_horse_required_task(self):
        memory, context, engine = self.make_engine()
        snap = snapshot(
            memory,
            state="MOVING",
            currentNodeId="S09",
            nextNodeId="S10",
            edgeProgressMs=1000,
            edgeTotalMs=20000,
            resources={"FAST_HORSE": 1},
            taskScore=60,
            tasks=[
                {
                    "taskId": "T06_1",
                    "nodeId": "S10",
                    "score": 30,
                    "active": True,
                    "requiredResourceTypes": ["FAST_HORSE"],
                }
            ],
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "MOVE", "targetNodeId": "S10"}])

    def test_waiting_without_next_node_returns_no_action(self):
        memory, context, engine = self.make_engine()
        snap = snapshot(memory, state="WAITING", currentNodeId="S01", nextNodeId=None)
        self.assertEqual(engine.decide(context, snap), [])

    def test_gate_verification_in_rush(self):
        memory, context, engine = self.make_engine()
        snap = snapshot(memory, phase="RUSH", currentNodeId="S14")
        self.assertEqual(engine.decide(context, snap), [{"action": "VERIFY_GATE"}])

    def test_gate_verification_binds_break_order_when_bad_fruit_available(self):
        memory, context, engine = self.make_engine()
        snap = snapshot(
            memory,
            phase="RUSH",
            currentNodeId="S14",
            badFruit=2,
            rushTacticUsedCount=0,
        )

        self.assertEqual(
            engine.decide(context, snap),
            [{"action": "VERIFY_GATE", "targetNodeId": "S14", "rushTactic": "BREAK_ORDER"}],
        )
        self.assertIn("BREAK_ORDER", engine.last_reason)

    def test_gate_verification_does_not_bind_break_order_after_tactic_used(self):
        memory, context, engine = self.make_engine()
        snap = snapshot(
            memory,
            phase="RUSH",
            currentNodeId="S14",
            badFruit=2,
            rushTacticUsedCount=1,
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "VERIFY_GATE"}])

    def test_gate_verification_does_not_spend_good_fruit_for_break_order(self):
        memory, context, engine = self.make_engine()
        snap = snapshot(
            memory,
            phase="RUSH",
            currentNodeId="S14",
            goodFruit=100,
            badFruit=0,
            rushTacticUsedCount=0,
        )

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

    def test_resource_gated_task_claims_required_resource_first(self):
        memory, context, engine = self.make_engine()
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S09", "resourceStock": {"FAST_HORSE": 1}},
            {"nodeId": "S10"},
            {"nodeId": "S14"},
            {"nodeId": "S15", "terminal": True},
        ]
        tasks = [
            {
                "taskId": "T06_006",
                "taskTemplateId": "T06",
                "nodeId": "S09",
                "score": 30,
                "active": True,
            }
        ]

        snap = snapshot(memory, currentNodeId="S09", taskScore=60, nodes=nodes, tasks=tasks)

        self.assertEqual(
            engine.decide(context, snap),
            [{"action": "CLAIM_RESOURCE", "targetNodeId": "S09", "resourceType": "FAST_HORSE"}],
        )

    def test_resource_gated_task_claims_when_resource_is_owned(self):
        memory, context, engine = self.make_engine()
        tasks = [
            {
                "taskId": "T06_006",
                "taskTemplateId": "T06",
                "nodeId": "S09",
                "score": 30,
                "active": True,
            }
        ]

        snap = snapshot(memory, currentNodeId="S09", taskScore=60, resources={"FAST_HORSE": 1}, tasks=tasks)

        self.assertEqual(engine.decide(context, snap), [{"action": "CLAIM_TASK", "taskId": "T06_006"}])

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

    def test_claims_process_node_task_before_fixed_process_when_safe(self):
        memory, context, engine = self.make_engine()
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S13", "processType": "PALACE_TRANSFER", "processRound": 5},
            {"nodeId": "S14", "processType": "VERIFY", "processRound": 6},
            {"nodeId": "S15", "terminal": True},
        ]
        tasks = [{"taskId": "T13_1", "nodeId": "S13", "score": 15, "processRound": 5, "active": True}]

        snap = snapshot(
            memory,
            round_no=430,
            currentNodeId="S13",
            taskScore=80,
            nodes=nodes,
            tasks=tasks,
            opponent_overrides={"playerId": 999, "currentNodeId": "S13", "state": "PROCESSING"},
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "CLAIM_TASK", "taskId": "T13_1"}])
        self.assertIn("before fixed process", engine.last_reason)

    def test_process_required_task_rejection_falls_back_to_fixed_process(self):
        memory, context, engine = self.make_engine()
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S13", "processType": "PALACE_TRANSFER", "processRound": 5},
            {"nodeId": "S14", "processType": "VERIFY", "processRound": 6},
            {"nodeId": "S15", "terminal": True},
        ]
        tasks = [{"taskId": "T13_1", "nodeId": "S13", "score": 15, "processRound": 5, "active": True}]
        rejected_task = {
            "playerId": 1001,
            "action": "CLAIM_TASK",
            "taskId": "T13_1",
            "errorCode": "PROCESS_REQUIRED",
            "accepted": False,
        }

        snap = snapshot(
            memory,
            round_no=431,
            currentNodeId="S13",
            nodes=nodes,
            tasks=tasks,
            action_results=[rejected_task],
            opponent_overrides={"playerId": 999, "currentNodeId": "S13", "state": "PROCESSING"},
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "PROCESS", "targetNodeId": "S13"}])

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

    def test_high_id_backs_off_after_process_contest_created(self):
        memory = GameMemory(2002)
        context = memory.apply_start(START)
        engine = DecisionEngine(memory)
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S02", "processType": "TRANSFER", "processRound": 4},
            {"nodeId": "S14"},
            {"nodeId": "S15", "terminal": True},
        ]
        contest_created = {
            "round": 43,
            "playerId": 2002,
            "action": "PROCESS",
            "accepted": True,
            "result": "ACCEPTED",
            "message": "CONTEST_CREATED",
        }

        snap = snapshot(
            memory,
            playerId=2002,
            teamId="BLUE",
            currentNodeId="S02",
            nodes=nodes,
            action_results=[contest_created],
            opponent_overrides={"playerId": 1001, "teamId": "RED", "currentNodeId": "S02", "state": "IDLE"},
        )

        self.assertEqual(engine.decide(context, snap), [])
        self.assertIn("back off process node S02", engine.last_reason)

    def test_process_contest_backoff_waits_while_opponent_is_busy(self):
        memory = GameMemory(2002)
        context = memory.apply_start(START)
        engine = DecisionEngine(memory)
        memory.process_contest_counts["S02"] = 1
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S02", "processType": "TRANSFER", "processRound": 4},
            {"nodeId": "S14"},
            {"nodeId": "S15", "terminal": True},
        ]

        snap = snapshot(
            memory,
            playerId=2002,
            teamId="BLUE",
            currentNodeId="S02",
            nodes=nodes,
            opponent_overrides={"playerId": 1001, "teamId": "RED", "currentNodeId": "S02", "state": "PROCESSING"},
        )

        self.assertEqual(engine.decide(context, snap), [])
        self.assertIn("wait after process contest", engine.last_reason)

    def test_high_id_waits_when_lower_id_occupies_same_fixed_process(self):
        memory, context, engine, nodes = self.make_replay_split_engine()
        snap = snapshot(
            memory,
            round_no=161,
            playerId=1002,
            teamId="BLUE",
            currentNodeId="S05",
            taskScore=30,
            nodes=nodes,
            opponent_overrides={
                "playerId": 1001,
                "teamId": "RED",
                "currentNodeId": "S05",
                "state": "PROCESSING",
                "currentProcess": {
                    "action": "PROCESS",
                    "objectKey": "PROCESS:S05:WATER_TRANSFER",
                    "targetNodeId": "S05",
                    "remainRound": 2,
                },
            },
        )

        self.assertEqual(engine.decide(context, snap), [])
        self.assertIn("occupying process node S05", engine.last_reason)

    def test_high_id_can_process_while_opponent_claims_task_at_process_node(self):
        memory, context, engine, nodes = self.make_replay_split_engine()
        nodes = [dict(node) for node in nodes]
        for node in nodes:
            if node["nodeId"] == "S11":
                node["processType"] = "PASS_TRANSFER"
                node["processRound"] = 5

        snap = snapshot(
            memory,
            round_no=344,
            playerId=1002,
            teamId="BLUE",
            currentNodeId="S11",
            taskScore=60,
            nodes=nodes,
            opponent_overrides={
                "playerId": 1001,
                "teamId": "RED",
                "currentNodeId": "S11",
                "state": "PROCESSING",
                "currentProcess": {
                    "action": "CLAIM_TASK",
                    "objectKey": "TASK:T12_012",
                    "targetNodeId": "S11",
                    "taskId": "T12_012",
                    "remainRound": 4,
                },
            },
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "PROCESS", "targetNodeId": "S11"}])

    def test_process_contest_backoff_is_bounded_when_opponent_stays_idle(self):
        memory = GameMemory(2002)
        context = memory.apply_start(START)
        engine = DecisionEngine(memory)
        memory.process_contest_counts["S02"] = 1
        memory.process_idle_yield_counts["S02"] = 1
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S02", "processType": "TRANSFER", "processRound": 4},
            {"nodeId": "S14"},
            {"nodeId": "S15", "terminal": True},
        ]

        snap = snapshot(
            memory,
            playerId=2002,
            teamId="BLUE",
            currentNodeId="S02",
            nodes=nodes,
            opponent_overrides={"playerId": 1001, "teamId": "RED", "currentNodeId": "S02", "state": "IDLE"},
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "PROCESS", "targetNodeId": "S02"}])

    def test_low_id_processes_after_recorded_contest_to_avoid_double_yield(self):
        memory, context, engine = self.make_engine()
        memory.process_contest_counts["S02"] = 1
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

    def test_skips_low_utility_resource_when_task_tempo_exists(self):
        memory, context, engine, nodes = self.make_delivery_map_engine()
        nodes = [dict(node) for node in nodes]
        for node in nodes:
            if node["nodeId"] == "S10":
                node["resourceStock"] = {"INTEL": 1}
        tasks = [{"taskId": "T12_012", "nodeId": "S11", "score": 15, "processRound": 5, "active": True}]

        snap = snapshot(memory, round_no=280, currentNodeId="S10", taskScore=80, nodes=nodes, tasks=tasks)

        self.assertEqual(engine.decide(context, snap), [{"action": "MOVE", "targetNodeId": "S11"}])
        self.assertIn("toward S11", engine.last_reason)

    def test_claims_utility_resource_when_it_unlocks_available_task(self):
        memory, context, engine = self.make_engine()
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S02", "resourceStock": {"PASS_TOKEN": 1}},
            {"nodeId": "S14"},
            {"nodeId": "S15", "terminal": True},
        ]
        tasks = [
            {
                "taskId": "T99_001",
                "nodeId": "S02",
                "score": 30,
                "active": True,
                "requiredResourceTypes": ["PASS_TOKEN"],
            }
        ]

        snap = snapshot(memory, currentNodeId="S02", taskScore=60, nodes=nodes, tasks=tasks)

        self.assertEqual(
            engine.decide(context, snap),
            [{"action": "CLAIM_RESOURCE", "targetNodeId": "S02", "resourceType": "PASS_TOKEN"}],
        )

    def test_defers_current_resource_gated_task_to_race_downstream_task(self):
        memory, context, engine, nodes = self.make_delivery_map_engine()
        nodes = [dict(node) for node in nodes]
        for node in nodes:
            if node["nodeId"] == "S09":
                node["resourceStock"] = {"FAST_HORSE": 1}
        tasks = [
            {
                "taskId": "T06_006",
                "taskTemplateId": "T06",
                "nodeId": "S09",
                "score": 30,
                "processType": "HORSE_TRANSFER",
                "processRound": 3,
                "requiredResourceTypes": ["FAST_HORSE"],
                "active": True,
            },
            {"taskId": "T11_011", "nodeId": "S10", "score": 30, "processRound": 4, "active": True},
        ]

        snap = snapshot(
            memory,
            round_no=214,
            currentNodeId="S09",
            taskScore=60,
            nodes=nodes,
            tasks=tasks,
            opponent_overrides={
                "playerId": 2002,
                "currentNodeId": "S09",
                "nextNodeId": "S10",
                "state": "MOVING",
                "edgeProgressMs": 2000,
                "edgeTotalMs": 55200,
            },
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "MOVE", "targetNodeId": "S10"}])
        self.assertIn("defer resource-gated task T06_006", engine.last_reason)

    def test_keeps_current_resource_gated_task_when_downstream_race_is_lost(self):
        memory, context, engine, nodes = self.make_delivery_map_engine()
        nodes = [dict(node) for node in nodes]
        for node in nodes:
            if node["nodeId"] == "S09":
                node["resourceStock"] = {"FAST_HORSE": 1}
        tasks = [
            {
                "taskId": "T06_006",
                "taskTemplateId": "T06",
                "nodeId": "S09",
                "score": 30,
                "processType": "HORSE_TRANSFER",
                "processRound": 3,
                "requiredResourceTypes": ["FAST_HORSE"],
                "active": True,
            },
            {"taskId": "T11_011", "nodeId": "S10", "score": 30, "processRound": 4, "active": True},
        ]

        snap = snapshot(
            memory,
            round_no=214,
            currentNodeId="S09",
            taskScore=60,
            nodes=nodes,
            tasks=tasks,
            opponent_overrides={
                "playerId": 2002,
                "currentNodeId": "S09",
                "nextNodeId": "S10",
                "state": "MOVING",
                "edgeProgressMs": 50000,
                "edgeTotalMs": 55200,
            },
        )

        self.assertEqual(
            engine.decide(context, snap),
            [{"action": "CLAIM_RESOURCE", "targetNodeId": "S09", "resourceType": "FAST_HORSE"}],
        )

    def test_resource_contest_created_skips_node_resources(self):
        memory, context, engine = self.make_engine()
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S02", "resourceStock": {"INTEL": 1}},
            {"nodeId": "S14"},
            {"nodeId": "S15", "terminal": True},
        ]
        contest_created = {
            "round": 98,
            "playerId": 1001,
            "action": "CLAIM_RESOURCE",
            "accepted": True,
            "result": "ACCEPTED",
            "message": "CONTEST_CREATED",
        }

        snap = snapshot(memory, currentNodeId="S02", nodes=nodes, action_results=[contest_created])

        self.assertIn("S02", memory.contested_resource_nodes)
        self.assertEqual(engine.decide(context, snap), [{"action": "MOVE", "targetNodeId": "S14"}])

    def test_resource_not_enough_rejection_records_depleted_resource(self):
        memory, context, engine = self.make_engine()
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S02", "resourceStock": {"FAST_HORSE": 1}},
            {"nodeId": "S14"},
            {"nodeId": "S15", "terminal": True},
        ]
        resource_complete = {
            "type": "PROCESS_COMPLETE",
            "payload": {
                "playerId": 1001,
                "action": "CLAIM_RESOURCE",
                "objectKey": "RESOURCE:S02:FAST_HORSE",
                "targetNodeId": "S02",
            },
        }
        resource_rejected = {
            "type": "ACTION_REJECTED",
            "payload": {"playerId": 1001, "action": "CLAIM_RESOURCE", "errorCode": "RESOURCE_NOT_ENOUGH"},
        }

        snap = snapshot(memory, currentNodeId="S02", nodes=nodes, events=[resource_complete, resource_rejected])

        self.assertIn(("S02", "FAST_HORSE"), memory.contested_resources)
        self.assertEqual(engine.decide(context, snap), [{"action": "MOVE", "targetNodeId": "S14"}])

    def test_resource_contest_on_other_node_does_not_skip_current_resource(self):
        memory, context, engine = self.make_engine()
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S02", "resourceStock": {"FAST_HORSE": 1}},
            {"nodeId": "S14"},
            {"nodeId": "S15", "terminal": True},
        ]
        other_node_contest = {
            "type": "WINDOW_CONTEST_START",
            "payload": {"contestType": "RESOURCE", "targetNodeId": "S03", "resourceType": "INTEL"},
        }

        snap = snapshot(memory, currentNodeId="S02", nodes=nodes, events=[other_node_contest])

        self.assertNotIn("S02", memory.contested_resource_nodes)
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

    def test_contests_current_resource_when_it_unlocks_high_value_current_task(self):
        memory, context, engine, nodes = self.make_delivery_map_engine()
        nodes = [dict(node) for node in nodes]
        for node in nodes:
            if node["nodeId"] == "S09":
                node["resourceStock"] = {"FAST_HORSE": 2}
        tasks = [
            {
                "taskId": "T06_006",
                "nodeId": "S09",
                "score": 30,
                "processRound": 3,
                "active": True,
                "requiredResourceTypes": ["FAST_HORSE"],
            },
            {"taskId": "T02_003", "nodeId": "S10", "score": 30, "processRound": 4, "active": True},
        ]

        snap = snapshot(
            memory,
            round_no=218,
            currentNodeId="S09",
            taskScore=30,
            nodes=nodes,
            tasks=tasks,
            opponent_overrides={
                "currentNodeId": "S09",
                "state": "PROCESSING",
                "currentProcess": {
                    "action": "CLAIM_RESOURCE",
                    "objectKey": "RESOURCE:S09:FAST_HORSE",
                    "targetNodeId": "S09",
                    "resourceType": "FAST_HORSE",
                    "remainRound": 1,
                },
            },
        )

        self.assertEqual(
            engine.decide(context, snap),
            [{"action": "CLAIM_RESOURCE", "targetNodeId": "S09", "resourceType": "FAST_HORSE"}],
        )
        self.assertIn("contest resource FAST_HORSE", engine.last_reason)

    def test_does_not_contest_singleton_current_resource_opponent_already_claiming(self):
        memory, context, engine, nodes = self.make_delivery_map_engine()
        nodes = [dict(node) for node in nodes]
        for node in nodes:
            if node["nodeId"] == "S09":
                node["resourceStock"] = {"FAST_HORSE": 1}
        tasks = [
            {
                "taskId": "T06_006",
                "nodeId": "S09",
                "score": 30,
                "processRound": 3,
                "active": True,
                "requiredResourceTypes": ["FAST_HORSE"],
            },
            {"taskId": "T02_003", "nodeId": "S10", "score": 30, "processRound": 4, "active": True},
        ]

        snap = snapshot(
            memory,
            round_no=218,
            currentNodeId="S09",
            taskScore=30,
            nodes=nodes,
            tasks=tasks,
            opponent_overrides={
                "currentNodeId": "S09",
                "state": "PROCESSING",
                "currentProcess": {
                    "action": "CLAIM_RESOURCE",
                    "objectKey": "RESOURCE:S09:FAST_HORSE",
                    "targetNodeId": "S09",
                    "resourceType": "FAST_HORSE",
                    "remainRound": 1,
                },
            },
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "MOVE", "targetNodeId": "S10"}])
        self.assertNotIn("contest resource FAST_HORSE", engine.last_reason)

    def test_does_not_contest_current_resource_for_low_value_task(self):
        memory, context, engine, nodes = self.make_delivery_map_engine()
        nodes = [dict(node) for node in nodes]
        for node in nodes:
            if node["nodeId"] == "S09":
                node["resourceStock"] = {"FAST_HORSE": 1}
        tasks = [
            {
                "taskId": "T12_LOW",
                "nodeId": "S09",
                "score": 15,
                "processRound": 5,
                "active": True,
                "requiredResourceTypes": ["FAST_HORSE"],
            }
        ]

        snap = snapshot(
            memory,
            round_no=218,
            currentNodeId="S09",
            taskScore=30,
            nodes=nodes,
            tasks=tasks,
            opponent_overrides={
                "currentNodeId": "S09",
                "state": "PROCESSING",
                "currentProcess": {
                    "action": "CLAIM_RESOURCE",
                    "objectKey": "RESOURCE:S09:FAST_HORSE",
                    "targetNodeId": "S09",
                    "resourceType": "FAST_HORSE",
                    "remainRound": 1,
                },
            },
        )

        self.assertNotEqual(
            engine.decide(context, snap),
            [{"action": "CLAIM_RESOURCE", "targetNodeId": "S09", "resourceType": "FAST_HORSE"}],
        )

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

    def test_current_threshold_task_preempts_dynamic_endgame_before_hard_lock(self):
        memory, context, engine, nodes = self.make_delivery_map_engine()
        tasks = [{"taskId": "T02_003", "nodeId": "S10", "score": 30, "processRound": 4, "active": True}]

        snap = snapshot(memory, round_no=416, currentNodeId="S10", taskScore=60, nodes=nodes, tasks=tasks)

        self.assertEqual(engine.decide(context, snap), [{"action": "CLAIM_TASK", "taskId": "T02_003"}])
        self.assertIn("threshold task", engine.last_reason)

    def test_current_threshold_task_does_not_override_hard_endgame_lock(self):
        memory, context, engine, nodes = self.make_delivery_map_engine()
        tasks = [{"taskId": "T02_003", "nodeId": "S10", "score": 30, "processRound": 4, "active": True}]

        snap = snapshot(memory, round_no=430, currentNodeId="S10", taskScore=60, nodes=nodes, tasks=tasks)

        self.assertEqual(engine.decide(context, snap), [{"action": "MOVE", "targetNodeId": "S11"}])
        self.assertIn("toward S14", engine.last_reason)

    def test_current_bonus_task_preempts_dynamic_endgame_after_target_score(self):
        memory, context, engine, nodes = self.make_delivery_map_engine()
        tasks = [{"taskId": "T11_011", "nodeId": "S10", "score": 30, "processRound": 4, "active": True}]

        snap = snapshot(memory, round_no=416, currentNodeId="S10", taskScore=90, nodes=nodes, tasks=tasks)

        self.assertEqual(engine.decide(context, snap), [{"action": "CLAIM_TASK", "taskId": "T11_011"}])
        self.assertIn("bonus task", engine.last_reason)

    def test_current_bonus_task_does_not_override_insufficient_delivery_slack(self):
        memory, context, engine, nodes = self.make_delivery_map_engine()
        tasks = [{"taskId": "T11_011", "nodeId": "S10", "score": 30, "processRound": 4, "active": True}]

        snap = snapshot(memory, round_no=424, currentNodeId="S10", taskScore=90, nodes=nodes, tasks=tasks)

        self.assertEqual(engine.decide(context, snap), [{"action": "MOVE", "targetNodeId": "S11"}])
        self.assertIn("toward S14", engine.last_reason)

    def test_skips_branch_task_when_delivery_slack_is_insufficient(self):
        memory, context, engine, nodes = self.make_delivery_map_engine()
        tasks = [
            {"taskId": "T02_003", "nodeId": "S10", "score": 30, "processRound": 4, "active": True},
            {"taskId": "T08_008", "nodeId": "S04", "score": 30, "processRound": 4, "active": True},
        ]

        snap = snapshot(memory, round_no=183, currentNodeId="S07", taskScore=60, nodes=nodes, tasks=tasks)

        self.assertEqual(engine.decide(context, snap), [{"action": "MOVE", "targetNodeId": "S09"}])
        self.assertIn("toward S10", engine.last_reason)

    def test_allows_branch_task_when_delivery_slack_is_sufficient(self):
        memory, context, engine, nodes = self.make_delivery_map_engine()
        tasks = [
            {"taskId": "T02_003", "nodeId": "S10", "score": 30, "processRound": 4, "active": True},
            {"taskId": "T08_008", "nodeId": "S04", "score": 30, "processRound": 4, "active": True},
        ]

        snap = snapshot(memory, round_no=10, currentNodeId="S07", taskScore=60, nodes=nodes, tasks=tasks)

        self.assertEqual(engine.decide(context, snap), [{"action": "MOVE", "targetNodeId": "S04"}])
        self.assertIn("toward S04", engine.last_reason)

    def test_replay_split_prefers_s04_task_cluster_over_s03_single_task(self):
        memory, context, engine, nodes = self.make_replay_split_engine()
        tasks = [
            {"taskId": "T01_001", "nodeId": "S03", "score": 30, "processRound": 3, "active": True},
            {"taskId": "T02_002", "nodeId": "S07", "score": 30, "processRound": 4, "active": True},
            {"taskId": "T06_007", "taskTemplateId": "T06", "nodeId": "S04", "score": 30, "processRound": 3, "active": True},
            {"taskId": "T08_008", "nodeId": "S04", "score": 30, "processRound": 4, "active": True},
            {"taskId": "T08_009", "nodeId": "S05", "score": 30, "processRound": 4, "active": True},
        ]

        snap = snapshot(
            memory,
            round_no=47,
            playerId=1002,
            teamId="BLUE",
            currentNodeId="S02",
            nodes=nodes,
            tasks=tasks,
            opponent_overrides={"playerId": 1001, "teamId": "RED", "currentNodeId": "S02", "state": "IDLE"},
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "MOVE", "targetNodeId": "S04"}])
        self.assertIn("toward S04", engine.last_reason)

    def test_replay_split_keeps_s04_when_opponent_lead_is_shallow(self):
        memory, context, engine, nodes = self.make_replay_split_engine()
        tasks = [
            {"taskId": "T01_001", "nodeId": "S03", "score": 30, "processRound": 3, "active": True},
            {"taskId": "T02_002", "nodeId": "S07", "score": 30, "processRound": 4, "active": True},
            {"taskId": "T06_007", "taskTemplateId": "T06", "nodeId": "S04", "score": 30, "processRound": 3, "active": True},
            {"taskId": "T08_008", "nodeId": "S04", "score": 30, "processRound": 4, "active": True},
            {"taskId": "T08_009", "nodeId": "S05", "score": 30, "processRound": 4, "active": True},
            {
                "taskId": "T06_006",
                "taskTemplateId": "T06",
                "nodeId": "S09",
                "score": 30,
                "processRound": 3,
                "active": True,
            },
        ]

        snap = snapshot(
            memory,
            round_no=55,
            playerId=1002,
            teamId="BLUE",
            currentNodeId="S02",
            nodes=nodes,
            tasks=tasks,
            opponent_overrides={
                "playerId": 1001,
                "teamId": "RED",
                "state": "MOVING",
                "currentNodeId": "S02",
                "nextNodeId": "S04",
                "edgeProgressMs": 4000,
                "edgeTotalMs": 27600,
            },
        )

        action = engine.decide(context, snap)
        self.assertEqual(action, [{"action": "MOVE", "targetNodeId": "S04"}])
        self.assertIn("toward S04", engine.last_reason)

    def test_replay_split_avoids_s04_when_opponent_is_clearly_ahead_to_process_node(self):
        memory, context, engine, nodes = self.make_replay_split_engine()
        tasks = [
            {"taskId": "T01_001", "nodeId": "S03", "score": 30, "processRound": 3, "active": True},
            {"taskId": "T02_002", "nodeId": "S07", "score": 30, "processRound": 4, "active": True},
            {"taskId": "T06_007", "taskTemplateId": "T06", "nodeId": "S04", "score": 30, "processRound": 3, "active": True},
            {"taskId": "T08_008", "nodeId": "S04", "score": 30, "processRound": 4, "active": True},
            {"taskId": "T08_009", "nodeId": "S05", "score": 30, "processRound": 4, "active": True},
            {
                "taskId": "T06_006",
                "taskTemplateId": "T06",
                "nodeId": "S09",
                "score": 30,
                "processRound": 3,
                "active": True,
            },
        ]

        snap = snapshot(
            memory,
            round_no=55,
            playerId=1002,
            teamId="BLUE",
            currentNodeId="S02",
            nodes=nodes,
            tasks=tasks,
            opponent_overrides={
                "playerId": 1001,
                "teamId": "RED",
                "state": "MOVING",
                "currentNodeId": "S02",
                "nextNodeId": "S04",
                "edgeProgressMs": 12000,
                "edgeTotalMs": 27600,
            },
        )

        action = engine.decide(context, snap)
        self.assertEqual(action, [{"action": "MOVE", "targetNodeId": "S03"}])
        self.assertNotEqual(action, [{"action": "MOVE", "targetNodeId": "S04"}])

    def test_horse_transfer_task_accepts_short_horse_requirement_option(self):
        memory, context, engine, nodes = self.make_replay_split_engine()
        memory.completed_process_nodes.add("S04")
        tasks = [
            {"taskId": "T06_007", "taskTemplateId": "T06", "nodeId": "S04", "score": 30, "processRound": 3, "active": True}
        ]

        snap = snapshot(
            memory,
            playerId=1002,
            teamId="BLUE",
            currentNodeId="S04",
            resources={"SHORT_HORSE": 1},
            nodes=nodes,
            tasks=tasks,
            opponent_overrides={"playerId": 1001, "teamId": "RED", "currentNodeId": "S02", "state": "IDLE"},
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "CLAIM_TASK", "taskId": "T06_007"}])

    def test_process_node_claims_current_task_before_fixed_process_without_opponent(self):
        memory, context, engine, nodes = self.make_replay_split_engine()
        memory.completed_process_nodes.add("S04")
        tasks = [{"taskId": "T08_009", "nodeId": "S05", "score": 30, "processRound": 4, "active": True}]

        snap = snapshot(
            memory,
            round_no=145,
            playerId=1002,
            teamId="BLUE",
            currentNodeId="S05",
            nodes=nodes,
            tasks=tasks,
            opponent_overrides={"playerId": 1001, "teamId": "RED", "currentNodeId": "S04", "state": "MOVING"},
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "CLAIM_TASK", "taskId": "T08_009"}])
        self.assertIn("before fixed process", engine.last_reason)

    def test_process_node_claims_current_resource_unlock_before_fixed_process(self):
        memory, context, engine, nodes = self.make_replay_split_engine()
        tasks = [
            {"taskId": "T06_007", "taskTemplateId": "T06", "nodeId": "S04", "score": 30, "processRound": 3, "active": True}
        ]

        snap = snapshot(
            memory,
            round_no=83,
            playerId=1002,
            teamId="BLUE",
            currentNodeId="S04",
            nodes=nodes,
            tasks=tasks,
            opponent_overrides={
                "playerId": 1001,
                "teamId": "RED",
                "currentNodeId": "S04",
                "state": "PROCESSING",
                "currentProcess": {"action": "PROCESS", "targetNodeId": "S04"},
            },
        )

        self.assertEqual(
            engine.decide(context, snap),
            [{"action": "CLAIM_RESOURCE", "targetNodeId": "S04", "resourceType": "SHORT_HORSE"}],
        )
        self.assertIn("before fixed process", engine.last_reason)

    def test_process_node_defers_resource_gated_task_to_race_downstream_task(self):
        memory, context, engine, nodes = self.make_replay_split_engine()
        tasks = [
            {"taskId": "T06_007", "taskTemplateId": "T06", "nodeId": "S04", "score": 30, "processRound": 3, "active": True},
            {"taskId": "T08_009", "nodeId": "S05", "score": 30, "processRound": 4, "active": True},
        ]

        snap = snapshot(
            memory,
            round_no=85,
            playerId=1002,
            teamId="BLUE",
            currentNodeId="S04",
            nodes=nodes,
            tasks=tasks,
            opponent_overrides={
                "playerId": 1001,
                "teamId": "RED",
                "currentNodeId": "S04",
                "state": "IDLE",
                "taskScore": 30,
            },
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "PROCESS", "targetNodeId": "S04"}])
        self.assertIn("defer resource-gated task T06_007", engine.last_reason)
        self.assertIn("T08_009", engine.last_reason)

    def test_process_node_contests_opponent_resource_unlock_before_fixed_process(self):
        memory, context, engine, nodes = self.make_replay_split_engine()
        nodes = [dict(node) for node in nodes]
        for node in nodes:
            if node["nodeId"] == "S04":
                node["resourceStock"] = {"SHORT_HORSE": 2}
        tasks = [
            {"taskId": "T06_007", "taskTemplateId": "T06", "nodeId": "S04", "score": 30, "processRound": 3, "active": True}
        ]

        snap = snapshot(
            memory,
            round_no=83,
            playerId=1002,
            teamId="BLUE",
            currentNodeId="S04",
            nodes=nodes,
            tasks=tasks,
            opponent_overrides={
                "playerId": 1001,
                "teamId": "RED",
                "currentNodeId": "S04",
                "state": "PROCESSING",
                "currentProcess": {
                    "action": "CLAIM_RESOURCE",
                    "objectKey": "RESOURCE:S04:SHORT_HORSE",
                    "targetNodeId": "S04",
                    "resourceType": "SHORT_HORSE",
                    "remainRound": 1,
                },
            },
        )

        self.assertEqual(
            engine.decide(context, snap),
            [{"action": "CLAIM_RESOURCE", "targetNodeId": "S04", "resourceType": "SHORT_HORSE"}],
        )
        self.assertIn("contest process-node resource SHORT_HORSE", engine.last_reason)

    def test_process_node_skips_singleton_resource_opponent_already_claiming(self):
        memory, context, engine, nodes = self.make_replay_split_engine()
        tasks = [
            {"taskId": "T06_007", "taskTemplateId": "T06", "nodeId": "S04", "score": 30, "processRound": 3, "active": True}
        ]

        snap = snapshot(
            memory,
            round_no=83,
            playerId=1002,
            teamId="BLUE",
            currentNodeId="S04",
            nodes=nodes,
            tasks=tasks,
            opponent_overrides={
                "playerId": 1001,
                "teamId": "RED",
                "currentNodeId": "S04",
                "state": "PROCESSING",
                "currentProcess": {
                    "action": "CLAIM_RESOURCE",
                    "objectKey": "RESOURCE:S04:SHORT_HORSE",
                    "targetNodeId": "S04",
                    "resourceType": "SHORT_HORSE",
                    "remainRound": 1,
                },
            },
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "PROCESS", "targetNodeId": "S04"}])

    def test_process_node_does_not_repeat_contested_resource_unlock_before_fixed_process(self):
        memory, context, engine, nodes = self.make_replay_split_engine()
        memory.contested_resource_nodes.add("S04")
        memory.contested_resources.add(("S04", "SHORT_HORSE"))
        tasks = [
            {"taskId": "T06_007", "taskTemplateId": "T06", "nodeId": "S04", "score": 30, "processRound": 3, "active": True}
        ]

        snap = snapshot(
            memory,
            round_no=84,
            playerId=1002,
            teamId="BLUE",
            currentNodeId="S04",
            nodes=nodes,
            tasks=tasks,
            opponent_overrides={
                "playerId": 1001,
                "teamId": "RED",
                "currentNodeId": "S04",
                "state": "PROCESSING",
                "currentProcess": {
                    "action": "CLAIM_RESOURCE",
                    "objectKey": "RESOURCE:S04:SHORT_HORSE",
                    "targetNodeId": "S04",
                    "resourceType": "SHORT_HORSE",
                },
            },
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "PROCESS", "targetNodeId": "S04"}])

    def test_process_node_does_not_contest_low_value_resource_unlock_before_fixed_process(self):
        memory, context, engine, nodes = self.make_replay_split_engine()
        tasks = [
            {"taskId": "T15_001", "taskTemplateId": "T06", "nodeId": "S04", "score": 15, "processRound": 3, "active": True}
        ]

        snap = snapshot(
            memory,
            round_no=83,
            playerId=1002,
            teamId="BLUE",
            currentNodeId="S04",
            nodes=nodes,
            tasks=tasks,
            opponent_overrides={
                "playerId": 1001,
                "teamId": "RED",
                "currentNodeId": "S04",
                "state": "PROCESSING",
                "currentProcess": {
                    "action": "CLAIM_RESOURCE",
                    "objectKey": "RESOURCE:S04:SHORT_HORSE",
                    "targetNodeId": "S04",
                    "resourceType": "SHORT_HORSE",
                },
            },
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "PROCESS", "targetNodeId": "S04"}])

    def test_process_node_claims_unlocked_current_task_before_fixed_process(self):
        memory, context, engine, nodes = self.make_replay_split_engine()
        tasks = [
            {"taskId": "T06_007", "taskTemplateId": "T06", "nodeId": "S04", "score": 30, "processRound": 3, "active": True},
            {"taskId": "T08_009", "nodeId": "S05", "score": 30, "processRound": 4, "active": True},
        ]

        snap = snapshot(
            memory,
            round_no=86,
            playerId=1002,
            teamId="BLUE",
            currentNodeId="S04",
            resources={"SHORT_HORSE": 1},
            nodes=nodes,
            tasks=tasks,
            opponent_overrides={"playerId": 1001, "teamId": "RED", "currentNodeId": "S04", "state": "PROCESSING"},
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "CLAIM_TASK", "taskId": "T06_007"}])
        self.assertIn("before fixed process", engine.last_reason)

    def test_known_process_required_task_still_processes_fixed_node_first(self):
        memory, context, engine, nodes = self.make_replay_split_engine()
        memory.process_required_task_ids.add("T08_009")
        tasks = [{"taskId": "T08_009", "nodeId": "S05", "score": 30, "processRound": 4, "active": True}]

        snap = snapshot(
            memory,
            round_no=145,
            playerId=1002,
            teamId="BLUE",
            currentNodeId="S05",
            nodes=nodes,
            tasks=tasks,
            opponent_overrides={"playerId": 1001, "teamId": "RED", "currentNodeId": "S04", "state": "MOVING"},
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "PROCESS", "targetNodeId": "S05"}])

    def test_routes_to_task_node_when_required_resource_is_available_there(self):
        memory, context, engine, nodes = self.make_delivery_map_engine()
        nodes = [dict(node) for node in nodes]
        for node in nodes:
            if node["nodeId"] == "S09":
                node["resourceStock"] = {"FAST_HORSE": 1}
        tasks = [
            {
                "taskId": "T06_006",
                "nodeId": "S09",
                "score": 30,
                "processRound": 3,
                "active": True,
                "requiredResourceTypes": ["FAST_HORSE"],
            },
            {"taskId": "T08_009", "nodeId": "S05", "score": 30, "processRound": 4, "active": True},
        ]

        snap = snapshot(memory, round_no=179, currentNodeId="S07", taskScore=60, nodes=nodes, tasks=tasks)

        self.assertEqual(engine.decide(context, snap), [{"action": "MOVE", "targetNodeId": "S09"}])
        self.assertIn("toward S09", engine.last_reason)

    def test_skips_costly_path_side_bonus_task_before_cluster_target(self):
        memory, context, engine, nodes = self.make_delivery_map_engine()
        memory.completed_process_nodes.add("S05")
        nodes = [dict(node) for node in nodes]
        for node in nodes:
            if node["nodeId"] == "S09":
                node["resourceStock"] = {"FAST_HORSE": 1}
        tasks = [
            {"taskId": "T02_002", "nodeId": "S07", "score": 30, "processRound": 4, "active": True},
            {
                "taskId": "T06_006",
                "nodeId": "S09",
                "score": 30,
                "processRound": 3,
                "active": True,
                "requiredResourceTypes": ["FAST_HORSE"],
            },
            {"taskId": "T11_011", "nodeId": "S10", "score": 30, "processRound": 4, "active": True},
        ]

        snap = snapshot(memory, round_no=151, currentNodeId="S05", taskScore=60, nodes=nodes, tasks=tasks)

        action = engine.decide(context, snap)
        self.assertEqual(action, [{"action": "MOVE", "targetNodeId": "S09"}])
        self.assertNotEqual(action, [{"action": "MOVE", "targetNodeId": "S07"}])
        self.assertIn("toward S09", engine.last_reason)

    def test_prefers_direct_corridor_task_before_branch_bonus_below_target(self):
        memory, context, engine, nodes = self.make_replay_split_engine()
        memory.completed_process_nodes.add("S04")
        nodes = [dict(node) for node in nodes]
        for node in nodes:
            if node["nodeId"] == "S04":
                node["resourceStock"] = {}
            elif node["nodeId"] == "S09":
                node["resourceStock"] = {"FAST_HORSE": 1}
        tasks = [
            {"taskId": "T02_002", "nodeId": "S07", "score": 30, "processRound": 4, "active": True},
            {"taskId": "T02_003", "nodeId": "S10", "score": 30, "processRound": 4, "active": True},
            {
                "taskId": "T06_006",
                "taskTemplateId": "T06",
                "nodeId": "S09",
                "score": 30,
                "processRound": 3,
                "active": True,
            },
            {"taskId": "T08_009", "nodeId": "S05", "score": 30, "processRound": 4, "active": True},
            {"taskId": "T11_011", "nodeId": "S10", "score": 30, "processRound": 4, "active": True},
        ]

        snap = snapshot(
            memory,
            round_no=94,
            playerId=1002,
            teamId="BLUE",
            currentNodeId="S04",
            taskScore=60,
            nodes=nodes,
            tasks=tasks,
            opponent_overrides={
                "playerId": 1001,
                "teamId": "RED",
                "state": "MOVING",
                "currentNodeId": "S04",
                "nextNodeId": "S05",
                "edgeProgressMs": 15000,
                "edgeTotalMs": 60720,
            },
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "MOVE", "targetNodeId": "S05"}])
        self.assertIn("direct corridor task node S05", engine.last_reason)

    def test_routes_to_bonus_task_after_task_score_target_when_slack_allows(self):
        memory, context, engine, nodes = self.make_delivery_map_engine()
        memory.completed_process_nodes.add("S05")
        tasks = [{"taskId": "T02_002", "nodeId": "S07", "score": 30, "processRound": 4, "active": True}]

        snap = snapshot(memory, round_no=151, currentNodeId="S05", taskScore=90, nodes=nodes, tasks=tasks)

        self.assertEqual(engine.decide(context, snap), [{"action": "MOVE", "targetNodeId": "S07"}])
        self.assertIn("bonus task node S07", engine.last_reason)

    def test_skips_path_side_bonus_task_when_delivery_slack_is_tight(self):
        memory, context, engine, nodes = self.make_delivery_map_engine()
        memory.completed_process_nodes.add("S05")
        nodes = [dict(node) for node in nodes]
        for node in nodes:
            if node["nodeId"] == "S09":
                node["resourceStock"] = {"FAST_HORSE": 1}
        tasks = [
            {"taskId": "T02_002", "nodeId": "S07", "score": 30, "processRound": 4, "active": True},
            {
                "taskId": "T06_006",
                "nodeId": "S09",
                "score": 30,
                "processRound": 3,
                "active": True,
                "requiredResourceTypes": ["FAST_HORSE"],
            },
            {"taskId": "T11_011", "nodeId": "S10", "score": 30, "processRound": 4, "active": True},
        ]

        snap = snapshot(memory, round_no=330, currentNodeId="S05", taskScore=60, nodes=nodes, tasks=tasks)

        self.assertEqual(engine.decide(context, snap), [{"action": "MOVE", "targetNodeId": "S09"}])
        self.assertIn("toward S14", engine.last_reason)

    def test_does_not_route_to_resource_gated_task_when_unlock_resource_is_absent(self):
        memory, context, engine, nodes = self.make_delivery_map_engine()
        tasks = [
            {
                "taskId": "T06_006",
                "nodeId": "S09",
                "score": 30,
                "processRound": 3,
                "active": True,
                "requiredResourceTypes": ["FAST_HORSE"],
            },
            {"taskId": "T08_009", "nodeId": "S05", "score": 30, "processRound": 4, "active": True},
        ]

        snap = snapshot(memory, round_no=179, currentNodeId="S07", taskScore=60, nodes=nodes, tasks=tasks)

        self.assertEqual(engine.decide(context, snap), [{"action": "MOVE", "targetNodeId": "S05"}])
        self.assertIn("toward S05", engine.last_reason)

    def test_skips_current_task_when_delivery_slack_is_insufficient(self):
        memory, context, engine, nodes = self.make_delivery_map_engine()
        memory.completed_process_nodes.add("S05")
        tasks = [{"taskId": "T08_009", "nodeId": "S05", "score": 30, "processRound": 4, "active": True}]

        snap = snapshot(memory, round_no=355, currentNodeId="S05", taskScore=80, nodes=nodes, tasks=tasks)

        self.assertEqual(engine.decide(context, snap), [{"action": "MOVE", "targetNodeId": "S09"}])
        self.assertIn("toward S14", engine.last_reason)

    def test_uses_ice_box_before_endgame_movement(self):
        memory, context, engine = self.make_engine()
        snap = snapshot(
            memory,
            round_no=430,
            currentNodeId="S09",
            freshness=80,
            resources={"ICE_BOX": 1},
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "USE_RESOURCE", "resourceType": "ICE_BOX"}])
        self.assertIn("use ICE_BOX before endgame", engine.last_reason)

    def test_does_not_use_ice_box_when_freshness_is_high(self):
        memory, context, engine = self.make_engine()
        snap = snapshot(
            memory,
            round_no=430,
            currentNodeId="S09",
            freshness=93,
            resources={"ICE_BOX": 1},
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "MOVE", "targetNodeId": "S10"}])

    def test_ice_box_does_not_block_gate_or_terminal(self):
        memory, context, engine = self.make_engine()
        gate = snapshot(
            memory,
            phase="RUSH",
            round_no=462,
            currentNodeId="S14",
            freshness=70,
            resources={"ICE_BOX": 1},
        )
        self.assertEqual(engine.decide(context, gate), [{"action": "VERIFY_GATE"}])

        terminal = snapshot(
            memory,
            phase="RUSH",
            round_no=482,
            currentNodeId="S15",
            freshness=70,
            verified=True,
            resources={"ICE_BOX": 1},
        )
        self.assertEqual(engine.decide(context, terminal), [{"action": "DELIVER"}])

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

    def test_defers_low_value_current_task_to_race_downstream_milestone_task(self):
        memory, context, engine, nodes = self.make_delivery_map_engine()
        tasks = [
            {"taskId": "T12_012", "nodeId": "S11", "score": 15, "processRound": 5, "active": True},
            {"taskId": "T13_013", "nodeId": "S13", "score": 15, "processRound": 5, "active": True},
        ]

        snap = snapshot(
            memory,
            round_no=332,
            currentNodeId="S11",
            taskScore=80,
            nodes=nodes,
            tasks=tasks,
            opponent_overrides={
                "playerId": 2002,
                "currentNodeId": "S10",
                "nextNodeId": "S11",
                "state": "MOVING",
                "edgeProgressMs": 48000,
                "edgeTotalMs": 49680,
            },
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "PROCESS", "targetNodeId": "S11"}])
        self.assertIn("defer low-value task T12_012", engine.last_reason)

    def test_claims_low_value_current_task_when_opponent_cannot_win_downstream_race(self):
        memory, context, engine, nodes = self.make_delivery_map_engine()
        tasks = [
            {"taskId": "T12_012", "nodeId": "S11", "score": 15, "processRound": 5, "active": True},
            {"taskId": "T13_013", "nodeId": "S13", "score": 15, "processRound": 5, "active": True},
        ]

        snap = snapshot(
            memory,
            round_no=332,
            currentNodeId="S11",
            taskScore=80,
            nodes=nodes,
            tasks=tasks,
            opponent_overrides={
                "playerId": 2002,
                "currentNodeId": "S10",
                "nextNodeId": "S11",
                "state": "MOVING",
                "edgeProgressMs": 0,
                "edgeTotalMs": 49680,
            },
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "CLAIM_TASK", "taskId": "T12_012"}])

    def test_does_not_defer_high_value_current_task_for_downstream_denial(self):
        memory, context, engine, nodes = self.make_delivery_map_engine()
        tasks = [
            {"taskId": "T11_011", "nodeId": "S11", "score": 30, "processRound": 4, "active": True},
            {"taskId": "T13_013", "nodeId": "S13", "score": 15, "processRound": 5, "active": True},
        ]

        snap = snapshot(
            memory,
            round_no=332,
            currentNodeId="S11",
            taskScore=80,
            nodes=nodes,
            tasks=tasks,
            opponent_overrides={
                "playerId": 2002,
                "currentNodeId": "S10",
                "nextNodeId": "S11",
                "state": "MOVING",
                "edgeProgressMs": 48000,
                "edgeTotalMs": 49680,
            },
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "CLAIM_TASK", "taskId": "T11_011"}])

    def test_task_contesting_prefers_xian_gong_to_break_bing_mirror(self):
        memory, context, engine = self.make_engine()
        contests = [{"contestId": "C1", "contestType": "TASK", "redPlayerId": 1001, "bluePlayerId": 2002, "roundIndex": 1}]
        snap = snapshot(memory, state="CONTESTING", currentNodeId="S02", contests=contests)
        self.assertEqual(engine.decide(context, snap), [{"action": "WINDOW_CARD", "contestId": "C1", "card": "XIAN_GONG"}])

    def test_task_window_falls_back_to_bing_when_xian_gong_is_unsafe(self):
        memory, context, engine = self.make_engine()
        contests = [{"contestId": "C1", "contestType": "TASK", "redPlayerId": 1001, "bluePlayerId": 2002, "roundIndex": 1}]
        snap = snapshot(memory, state="CONTESTING", currentNodeId="S02", contests=contests, freshness=79, goodFruit=100)
        self.assertEqual(engine.decide(context, snap), [{"action": "WINDOW_CARD", "contestId": "C1", "card": "BING_ZHENG"}])

    def test_window_counter_uses_xian_gong_against_seen_bing_zheng(self):
        memory, context, engine = self.make_engine()
        contests = [
            {
                "contestId": "C1",
                "contestType": "TASK",
                "redPlayerId": 1001,
                "bluePlayerId": 2002,
                "roundIndex": 2,
                "cards": {"R1:BLUE": "BING_ZHENG"},
            }
        ]
        snap = snapshot(memory, state="CONTESTING", currentNodeId="S02", contests=contests)
        self.assertEqual(engine.decide(context, snap), [{"action": "WINDOW_CARD", "contestId": "C1", "card": "XIAN_GONG"}])

    def test_window_counter_uses_qiang_xing_against_seen_xian_gong_when_affordable(self):
        memory, context, engine = self.make_engine()
        contests = [
            {
                "contestId": "C1",
                "contestType": "TASK",
                "redPlayerId": 1001,
                "bluePlayerId": 2002,
                "roundIndex": 2,
                "cards": {"R1:BLUE": "XIAN_GONG"},
            }
        ]
        snap = snapshot(
            memory,
            state="CONTESTING",
            currentNodeId="S02",
            contests=contests,
            resources={"FAST_HORSE": 1},
        )
        self.assertEqual(engine.decide(context, snap), [{"action": "WINDOW_CARD", "contestId": "C1", "card": "QIANG_XING"}])

    def test_high_id_abstains_after_xian_gong_in_fixed_process_window(self):
        memory = GameMemory(2002)
        context = memory.apply_start(START)
        engine = DecisionEngine(memory)
        contests = [
            {
                "contestId": "C1",
                "contestType": "DOCK",
                "redPlayerId": 1001,
                "bluePlayerId": 2002,
                "objectKey": "PROCESS:S02:TRANSFER",
                "sourceActionTypes": {"1001": "PROCESS", "2002": "PROCESS"},
                "cards": {"R1:RED": "XIAN_GONG"},
            }
        ]

        snap = snapshot(
            memory,
            playerId=2002,
            teamId="BLUE",
            state="CONTESTING",
            currentNodeId="S02",
            contests=contests,
            opponent_overrides={"playerId": 1001, "teamId": "RED", "currentNodeId": "S02"},
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "WINDOW_CARD", "contestId": "C1", "card": "ABSTAIN"}])

    def test_high_id_keeps_xian_gong_for_early_process_corridor_without_qiang_xing(self):
        memory, context, engine, nodes = self.make_replay_split_engine()
        contests = [
            {
                "contestId": "C1",
                "contestType": "DOCK",
                "redPlayerId": 1001,
                "bluePlayerId": 1002,
                "objectKey": "PROCESS:S02:TRANSFER",
                "sourceActionTypes": {"1001": "PROCESS", "1002": "PROCESS"},
                "cards": {"R1:RED": "XIAN_GONG"},
            }
        ]
        tasks = [
            {"taskId": "T06_007", "taskTemplateId": "T06", "nodeId": "S04", "score": 30, "processRound": 3, "active": True},
            {"taskId": "T08_009", "nodeId": "S05", "score": 30, "processRound": 4, "active": True},
        ]

        snap = snapshot(
            memory,
            round_no=45,
            playerId=1002,
            teamId="BLUE",
            state="CONTESTING",
            currentNodeId="S02",
            nodes=nodes,
            tasks=tasks,
            contests=contests,
            opponent_overrides={"playerId": 1001, "teamId": "RED", "currentNodeId": "S02"},
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "WINDOW_CARD", "contestId": "C1", "card": "XIAN_GONG"}])

    def test_high_id_keeps_xian_gong_for_critical_s05_process_corridor(self):
        memory, context, engine, nodes = self.make_replay_split_engine()
        nodes = [dict(node) for node in nodes]
        for node in nodes:
            if node["nodeId"] == "S09":
                node["resourceStock"] = {"FAST_HORSE": 1}
        contests = [
            {
                "contestId": "C1",
                "contestType": "DOCK",
                "redPlayerId": 1001,
                "bluePlayerId": 1002,
                "objectKey": "PROCESS:S05:WATER_TRANSFER",
                "sourceActionTypes": {"1001": "PROCESS", "1002": "PROCESS"},
                "cards": {"R1:RED": "XIAN_GONG"},
            }
        ]
        tasks = [
            {
                "taskId": "T06_006",
                "taskTemplateId": "T06",
                "nodeId": "S09",
                "score": 30,
                "processRound": 3,
                "active": True,
                "requiredResourceTypes": ["FAST_HORSE"],
            },
            {"taskId": "T11_011", "nodeId": "S10", "score": 30, "processRound": 4, "active": True},
        ]

        snap = snapshot(
            memory,
            round_no=151,
            playerId=1002,
            teamId="BLUE",
            state="CONTESTING",
            currentNodeId="S05",
            taskScore=30,
            nodes=nodes,
            tasks=tasks,
            contests=contests,
            opponent_overrides={"playerId": 1001, "teamId": "RED", "currentNodeId": "S05"},
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "WINDOW_CARD", "contestId": "C1", "card": "XIAN_GONG"}])

    def test_fixed_process_window_uses_bing_when_only_guard_card_is_affordable(self):
        memory, context, engine, nodes = self.make_replay_split_engine()
        contests = [
            {
                "contestId": "C1",
                "contestType": "DOCK",
                "redPlayerId": 1001,
                "bluePlayerId": 1002,
                "objectKey": "PROCESS:S13:PALACE_TRANSFER",
                "sourceActionTypes": {"1001": "PROCESS", "1002": "PROCESS"},
            }
        ]

        snap = snapshot(
            memory,
            round_no=408,
            playerId=1002,
            teamId="BLUE",
            state="CONTESTING",
            currentNodeId="S13",
            freshness=75,
            goodFruit=95,
            taskScore=80,
            nodes=nodes,
            contests=contests,
            opponent_overrides={"playerId": 1001, "teamId": "RED", "currentNodeId": "S13"},
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "WINDOW_CARD", "contestId": "C1", "card": "BING_ZHENG"}])

    def test_fixed_process_window_abstains_when_guard_card_is_not_affordable(self):
        memory, context, engine, nodes = self.make_replay_split_engine()
        contests = [
            {
                "contestId": "C1",
                "contestType": "DOCK",
                "redPlayerId": 1001,
                "bluePlayerId": 1002,
                "objectKey": "PROCESS:S13:PALACE_TRANSFER",
                "sourceActionTypes": {"1001": "PROCESS", "1002": "PROCESS"},
            }
        ]

        snap = snapshot(
            memory,
            round_no=408,
            playerId=1002,
            teamId="BLUE",
            state="CONTESTING",
            currentNodeId="S13",
            freshness=75,
            goodFruit=95,
            guardActionPoint=0,
            taskScore=80,
            nodes=nodes,
            contests=contests,
            opponent_overrides={"playerId": 1001, "teamId": "RED", "currentNodeId": "S13"},
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "WINDOW_CARD", "contestId": "C1", "card": "ABSTAIN"}])

    def test_late_fixed_process_window_still_abstains_after_xian_gong(self):
        memory, context, engine, nodes = self.make_replay_split_engine()
        contests = [
            {
                "contestId": "C1",
                "contestType": "DOCK",
                "redPlayerId": 1001,
                "bluePlayerId": 1002,
                "objectKey": "PROCESS:S02:TRANSFER",
                "sourceActionTypes": {"1001": "PROCESS", "1002": "PROCESS"},
                "cards": {"R1:RED": "XIAN_GONG"},
            }
        ]
        tasks = [{"taskId": "T08_009", "nodeId": "S05", "score": 30, "processRound": 4, "active": True}]

        snap = snapshot(
            memory,
            round_no=260,
            playerId=1002,
            teamId="BLUE",
            state="CONTESTING",
            currentNodeId="S02",
            nodes=nodes,
            tasks=tasks,
            contests=contests,
            opponent_overrides={"playerId": 1001, "teamId": "RED", "currentNodeId": "S02"},
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "WINDOW_CARD", "contestId": "C1", "card": "ABSTAIN"}])

    def test_late_critical_process_corridor_still_abstains_after_xian_gong(self):
        memory, context, engine, nodes = self.make_replay_split_engine()
        nodes = [dict(node) for node in nodes]
        for node in nodes:
            if node["nodeId"] == "S09":
                node["resourceStock"] = {"FAST_HORSE": 1}
        contests = [
            {
                "contestId": "C1",
                "contestType": "DOCK",
                "redPlayerId": 1001,
                "bluePlayerId": 1002,
                "objectKey": "PROCESS:S05:WATER_TRANSFER",
                "sourceActionTypes": {"1001": "PROCESS", "1002": "PROCESS"},
                "cards": {"R1:RED": "XIAN_GONG"},
            }
        ]
        tasks = [
            {
                "taskId": "T06_006",
                "taskTemplateId": "T06",
                "nodeId": "S09",
                "score": 30,
                "processRound": 3,
                "active": True,
                "requiredResourceTypes": ["FAST_HORSE"],
            }
        ]

        snap = snapshot(
            memory,
            round_no=260,
            playerId=1002,
            teamId="BLUE",
            state="CONTESTING",
            currentNodeId="S05",
            taskScore=30,
            nodes=nodes,
            tasks=tasks,
            contests=contests,
            opponent_overrides={"playerId": 1001, "teamId": "RED", "currentNodeId": "S05"},
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "WINDOW_CARD", "contestId": "C1", "card": "ABSTAIN"}])

    def test_high_id_uses_qiang_xing_counter_in_fixed_process_window_when_affordable(self):
        memory = GameMemory(2002)
        context = memory.apply_start(START)
        engine = DecisionEngine(memory)
        contests = [
            {
                "contestId": "C1",
                "contestType": "DOCK",
                "redPlayerId": 1001,
                "bluePlayerId": 2002,
                "objectKey": "PROCESS:S02:TRANSFER",
                "sourceActionTypes": {"1001": "PROCESS", "2002": "PROCESS"},
                "cards": {"R1:RED": "XIAN_GONG"},
            }
        ]

        snap = snapshot(
            memory,
            playerId=2002,
            teamId="BLUE",
            state="CONTESTING",
            currentNodeId="S02",
            contests=contests,
            resources={"FAST_HORSE": 1},
            opponent_overrides={"playerId": 1001, "teamId": "RED", "currentNodeId": "S02"},
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "WINDOW_CARD", "contestId": "C1", "card": "QIANG_XING"}])

    def test_low_id_keeps_xian_gong_pressure_in_fixed_process_window(self):
        memory, context, engine = self.make_engine()
        contests = [
            {
                "contestId": "C1",
                "contestType": "DOCK",
                "redPlayerId": 1001,
                "bluePlayerId": 2002,
                "objectKey": "PROCESS:S02:TRANSFER",
                "sourceActionTypes": {"1001": "PROCESS", "2002": "PROCESS"},
                "cards": {"R1:BLUE": "XIAN_GONG"},
            }
        ]

        snap = snapshot(memory, state="CONTESTING", currentNodeId="S02", contests=contests)

        self.assertEqual(engine.decide(context, snap), [{"action": "WINDOW_CARD", "contestId": "C1", "card": "XIAN_GONG"}])

    def test_fixed_process_window_leader_banks_lead_after_opponent_abstains(self):
        memory, context, engine = self.make_engine()
        contests = [
            {
                "contestId": "C1",
                "contestType": "DOCK",
                "redPlayerId": 1001,
                "bluePlayerId": 2002,
                "objectKey": "PROCESS:S02:TRANSFER",
                "sourceActionTypes": {"1001": "PROCESS", "2002": "PROCESS"},
                "redPoint": 1,
                "bluePoint": 0,
                "cards": {"R1:BLUE": "XIAN_GONG", "R2:BLUE": "ABSTAIN"},
            }
        ]

        snap = snapshot(memory, state="CONTESTING", currentNodeId="S02", contests=contests)

        self.assertEqual(engine.decide(context, snap), [{"action": "WINDOW_CARD", "contestId": "C1", "card": "ABSTAIN"}])

    def test_high_id_covers_final_process_lead_after_opponent_abstains(self):
        memory = GameMemory(2002)
        context = memory.apply_start(START)
        engine = DecisionEngine(memory)
        contests = [
            {
                "contestId": "C1",
                "contestType": "DOCK",
                "redPlayerId": 1001,
                "bluePlayerId": 2002,
                "objectKey": "PROCESS:S02:TRANSFER",
                "sourceActionTypes": {"1001": "PROCESS", "2002": "PROCESS"},
                "roundIndex": 3,
                "totalRounds": 3,
                "redPoint": 0,
                "bluePoint": 1,
                "cards": {
                    "R1:RED": "XIAN_GONG",
                    "R1:BLUE": "XIAN_GONG",
                    "R2:RED": "ABSTAIN",
                    "R2:BLUE": "XIAN_GONG",
                },
            }
        ]

        snap = snapshot(
            memory,
            playerId=2002,
            teamId="BLUE",
            state="CONTESTING",
            currentNodeId="S02",
            contests=contests,
            opponent_overrides={"playerId": 1001, "teamId": "RED", "currentNodeId": "S02"},
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "WINDOW_CARD", "contestId": "C1", "card": "XIAN_GONG"}])

    def test_final_process_lead_uses_bing_when_xian_gong_unaffordable(self):
        memory = GameMemory(2002)
        context = memory.apply_start(START)
        engine = DecisionEngine(memory)
        contests = [
            {
                "contestId": "C1",
                "contestType": "DOCK",
                "redPlayerId": 1001,
                "bluePlayerId": 2002,
                "objectKey": "PROCESS:S02:TRANSFER",
                "sourceActionTypes": {"1001": "PROCESS", "2002": "PROCESS"},
                "roundIndex": 3,
                "totalRounds": 3,
                "redPoint": 0,
                "bluePoint": 1,
                "cards": {
                    "R1:RED": "BING_ZHENG",
                    "R1:BLUE": "BING_ZHENG",
                    "R2:RED": "ABSTAIN",
                    "R2:BLUE": "BING_ZHENG",
                },
            }
        ]

        snap = snapshot(
            memory,
            playerId=2002,
            teamId="BLUE",
            state="CONTESTING",
            currentNodeId="S02",
            freshness=75,
            goodFruit=95,
            guardActionPoint=2,
            contests=contests,
            opponent_overrides={"playerId": 1001, "teamId": "RED", "currentNodeId": "S02"},
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "WINDOW_CARD", "contestId": "C1", "card": "BING_ZHENG"}])

    def test_high_id_banks_process_lead_before_final_window_round(self):
        memory = GameMemory(2002)
        context = memory.apply_start(START)
        engine = DecisionEngine(memory)
        contests = [
            {
                "contestId": "C1",
                "contestType": "DOCK",
                "redPlayerId": 1001,
                "bluePlayerId": 2002,
                "objectKey": "PROCESS:S02:TRANSFER",
                "sourceActionTypes": {"1001": "PROCESS", "2002": "PROCESS"},
                "roundIndex": 2,
                "totalRounds": 3,
                "redPoint": 0,
                "bluePoint": 1,
                "cards": {"R1:RED": "ABSTAIN", "R1:BLUE": "XIAN_GONG"},
            }
        ]

        snap = snapshot(
            memory,
            playerId=2002,
            teamId="BLUE",
            state="CONTESTING",
            currentNodeId="S02",
            contests=contests,
            opponent_overrides={"playerId": 1001, "teamId": "RED", "currentNodeId": "S02"},
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "WINDOW_CARD", "contestId": "C1", "card": "ABSTAIN"}])

    def test_task_window_still_mirrors_xian_gong_when_no_counter_is_available(self):
        memory = GameMemory(2002)
        context = memory.apply_start(START)
        engine = DecisionEngine(memory)
        contests = [
            {
                "contestId": "C1",
                "contestType": "TASK",
                "redPlayerId": 1001,
                "bluePlayerId": 2002,
                "cards": {"R1:RED": "XIAN_GONG"},
            }
        ]

        snap = snapshot(
            memory,
            playerId=2002,
            teamId="BLUE",
            state="CONTESTING",
            currentNodeId="S02",
            contests=contests,
            opponent_overrides={"playerId": 1001, "teamId": "RED", "currentNodeId": "S02"},
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "WINDOW_CARD", "contestId": "C1", "card": "XIAN_GONG"}])

    def test_window_counter_abstains_when_seen_card_cannot_be_matched_or_beaten(self):
        memory, context, engine = self.make_engine()
        contests = [
            {
                "contestId": "C1",
                "contestType": "TASK",
                "redPlayerId": 1001,
                "bluePlayerId": 2002,
                "roundIndex": 2,
                "cards": {"R1:BLUE": "XIAN_GONG"},
            }
        ]
        snap = snapshot(
            memory,
            state="CONTESTING",
            currentNodeId="S02",
            contests=contests,
            freshness=79,
            goodFruit=100,
        )
        self.assertEqual(engine.decide(context, snap), [{"action": "WINDOW_CARD", "contestId": "C1", "card": "ABSTAIN"}])

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
