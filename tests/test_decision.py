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

    def test_moving_waits_when_next_node_gets_enemy_guard(self):
        memory, context, engine = self.make_engine()
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S02", "guard": {"ownerTeamId": "BLUE", "defense": 4, "active": True}},
            {"nodeId": "S14"},
            {"nodeId": "S15", "terminal": True},
        ]
        snap = snapshot(memory, state="MOVING", currentNodeId="S01", nextNodeId="S02", nodes=nodes)
        self.assertEqual(engine.decide(context, snap), [{"action": "WAIT"}])

    def test_moving_reroutes_from_edge_origin_when_alternate_neighbor_is_available(self):
        start = {
            "matchId": "m1",
            "round": 1,
            "durationRound": 600,
            "players": [{"playerId": 1001, "teamId": "RED"}, {"playerId": 2002, "teamId": "BLUE"}],
            "map": {"gameplay": {"roles": {"startNodeId": "S01", "gateNodeId": "S14", "terminalNodeIds": ["S15"]}}},
            "nodes": [
                {"nodeId": "S01", "start": True},
                {"nodeId": "S02", "guard": {"ownerTeamId": "BLUE", "defense": 4, "active": True}},
                {"nodeId": "S03"},
                {"nodeId": "S14"},
                {"nodeId": "S15", "terminal": True},
            ],
            "edges": [
                {"edgeId": "E1", "fromNodeId": "S01", "toNodeId": "S02", "routeType": "ROAD", "distance": 1},
                {"edgeId": "E2", "fromNodeId": "S02", "toNodeId": "S14", "routeType": "ROAD", "distance": 1},
                {"edgeId": "E3", "fromNodeId": "S01", "toNodeId": "S03", "routeType": "ROAD", "distance": 1},
                {"edgeId": "E4", "fromNodeId": "S03", "toNodeId": "S14", "routeType": "ROAD", "distance": 1},
                {"edgeId": "E5", "fromNodeId": "S14", "toNodeId": "S15", "routeType": "ROAD", "distance": 1},
            ],
        }
        memory = GameMemory(1001)
        context = memory.apply_start(start)
        engine = DecisionEngine(memory)

        snap = snapshot(
            memory,
            state="MOVING",
            currentNodeId="S01",
            nextNodeId="S02",
            taskScore=90,
            nodes=start["nodes"],
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "MOVE", "targetNodeId": "S03"}])
        self.assertIn("reroute", engine.last_reason)

    def test_moving_uses_squad_weaken_when_next_node_gets_enemy_guard(self):
        memory, context, engine = self.make_engine()
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S02", "guard": {"ownerTeamId": "BLUE", "defense": 4, "active": True}},
            {"nodeId": "S14"},
            {"nodeId": "S15", "terminal": True},
        ]
        snap = snapshot(
            memory,
            state="MOVING",
            currentNodeId="S01",
            nextNodeId="S02",
            squadAvailable=2,
            nodes=nodes,
        )
        self.assertEqual(
            engine.decide(context, snap),
            [{"action": "WAIT"}, {"action": "SQUAD_WEAKEN", "targetNodeId": "S02"}],
        )

    def test_moving_waits_and_squad_clears_when_next_node_gets_obstacle(self):
        memory, context, engine = self.make_engine()
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S02", "hasObstacle": True},
            {"nodeId": "S14"},
            {"nodeId": "S15", "terminal": True},
        ]
        snap = snapshot(
            memory,
            state="MOVING",
            currentNodeId="S01",
            nextNodeId="S02",
            squadAvailable=2,
            nodes=nodes,
        )
        self.assertEqual(
            engine.decide(context, snap),
            [{"action": "WAIT"}, {"action": "SQUAD_CLEAR", "targetNodeId": "S02"}],
        )

    def test_waiting_without_next_node_returns_no_action(self):
        memory, context, engine = self.make_engine()
        snap = snapshot(memory, state="WAITING", currentNodeId="S01", nextNodeId=None)
        self.assertEqual(engine.decide(context, snap), [])

    def test_idle_breaks_adjacent_enemy_guard_instead_of_moving_into_it(self):
        memory, context, engine = self.make_engine()
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S02", "guard": {"ownerTeamId": "BLUE", "defense": 3, "active": True}},
            {"nodeId": "S14"},
            {"nodeId": "S15", "terminal": True},
        ]
        snap = snapshot(memory, currentNodeId="S01", taskScore=90, badFruit=1, nodes=nodes)
        self.assertEqual(
            engine.decide(context, snap),
            [{"action": "BREAK_GUARD", "targetNodeId": "S02", "badFruit": 1}],
        )

    def test_idle_force_passes_guard_when_break_guard_cannot_succeed(self):
        memory, context, engine = self.make_engine()
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S02", "guard": {"ownerTeamId": "BLUE", "defense": 7, "active": True}},
            {"nodeId": "S14"},
            {"nodeId": "S15", "terminal": True},
        ]
        snap = snapshot(memory, currentNodeId="S01", taskScore=90, goodFruit=8, badFruit=0, nodes=nodes)
        self.assertEqual(engine.decide(context, snap), [{"action": "FORCED_PASS", "targetNodeId": "S02"}])

    def test_no_new_squad_action_in_rush(self):
        memory, context, engine = self.make_engine()
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S02", "guard": {"ownerTeamId": "BLUE", "defense": 4, "active": True}},
            {"nodeId": "S14"},
            {"nodeId": "S15", "terminal": True},
        ]
        snap = snapshot(
            memory,
            phase="RUSH",
            state="MOVING",
            currentNodeId="S01",
            nextNodeId="S02",
            squadAvailable=8,
            nodes=nodes,
        )
        self.assertEqual(engine.decide(context, snap), [{"action": "WAIT"}])

    def test_idle_avoids_route_node_where_opponent_can_finish_guard_first(self):
        start = {
            "matchId": "m1",
            "round": 1,
            "durationRound": 600,
            "players": [{"playerId": 1001, "teamId": "RED"}, {"playerId": 2002, "teamId": "BLUE"}],
            "map": {"gameplay": {"roles": {"startNodeId": "S01", "gateNodeId": "S14", "terminalNodeIds": ["S15"]}}},
            "nodes": [
                {"nodeId": "S01", "start": True},
                {"nodeId": "S02", "nodeType": "KEY_PASS"},
                {"nodeId": "S03"},
                {"nodeId": "S14"},
                {"nodeId": "S15", "terminal": True},
            ],
            "edges": [
                {"edgeId": "E1", "fromNodeId": "S01", "toNodeId": "S02", "routeType": "ROAD", "distance": 5},
                {"edgeId": "E2", "fromNodeId": "S02", "toNodeId": "S14", "routeType": "ROAD", "distance": 1},
                {"edgeId": "E3", "fromNodeId": "S01", "toNodeId": "S03", "routeType": "ROAD", "distance": 4},
                {"edgeId": "E4", "fromNodeId": "S03", "toNodeId": "S14", "routeType": "ROAD", "distance": 4},
                {"edgeId": "E5", "fromNodeId": "S14", "toNodeId": "S15", "routeType": "ROAD", "distance": 1},
            ],
        }
        memory = GameMemory(1001)
        context = memory.apply_start(start)
        engine = DecisionEngine(memory)

        snap = snapshot(
            memory,
            currentNodeId="S01",
            taskScore=90,
            nodes=start["nodes"],
            opponent_overrides={"currentNodeId": "S02", "state": "IDLE"},
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "MOVE", "targetNodeId": "S03"}])

    def test_idle_takes_fast_route_when_opponent_cannot_guard_before_arrival(self):
        start = {
            "matchId": "m1",
            "round": 1,
            "durationRound": 600,
            "players": [{"playerId": 1001, "teamId": "RED"}, {"playerId": 2002, "teamId": "BLUE"}],
            "map": {"gameplay": {"roles": {"startNodeId": "S01", "gateNodeId": "S14", "terminalNodeIds": ["S15"]}}},
            "nodes": [
                {"nodeId": "S01", "start": True},
                {"nodeId": "S02", "nodeType": "KEY_PASS"},
                {"nodeId": "S03"},
                {"nodeId": "S14"},
                {"nodeId": "S15", "terminal": True},
            ],
            "edges": [
                {"edgeId": "E1", "fromNodeId": "S01", "toNodeId": "S02", "routeType": "ROAD", "distance": 1},
                {"edgeId": "E2", "fromNodeId": "S02", "toNodeId": "S14", "routeType": "ROAD", "distance": 1},
                {"edgeId": "E3", "fromNodeId": "S01", "toNodeId": "S03", "routeType": "ROAD", "distance": 4},
                {"edgeId": "E4", "fromNodeId": "S03", "toNodeId": "S14", "routeType": "ROAD", "distance": 4},
                {"edgeId": "E5", "fromNodeId": "S14", "toNodeId": "S15", "routeType": "ROAD", "distance": 1},
            ],
        }
        memory = GameMemory(1001)
        context = memory.apply_start(start)
        engine = DecisionEngine(memory)

        snap = snapshot(
            memory,
            currentNodeId="S01",
            taskScore=90,
            nodes=start["nodes"],
            opponent_overrides={"currentNodeId": "S02", "state": "IDLE"},
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "MOVE", "targetNodeId": "S02"}])

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

    def test_avoids_same_node_task_contest_without_qiang_xing_counter(self):
        memory, context, engine = self.make_engine()
        tasks = [
            {"taskId": "T11_011", "nodeId": "S02", "score": 30, "active": True},
            {"taskId": "T14_014", "nodeId": "S02", "score": 15, "active": True},
        ]

        snap = snapshot(
            memory,
            currentNodeId="S02",
            taskScore=80,
            tasks=tasks,
            opponent_overrides={"currentNodeId": "S02", "state": "IDLE", "freshness": 84, "goodFruit": 94},
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "CLAIM_TASK", "taskId": "T14_014"}])

    def test_same_node_task_contest_allowed_without_alternate_task(self):
        memory, context, engine = self.make_engine()
        tasks = [{"taskId": "T11_011", "nodeId": "S02", "score": 30, "active": True}]

        snap = snapshot(
            memory,
            currentNodeId="S02",
            taskScore=80,
            tasks=tasks,
            opponent_overrides={"currentNodeId": "S02", "state": "IDLE", "freshness": 84, "goodFruit": 94},
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "CLAIM_TASK", "taskId": "T11_011"}])

    def test_same_node_task_contest_allowed_with_qiang_xing_counter(self):
        memory, context, engine = self.make_engine()
        tasks = [
            {"taskId": "T11_011", "nodeId": "S02", "score": 30, "active": True},
            {"taskId": "T14_014", "nodeId": "S02", "score": 15, "active": True},
        ]

        snap = snapshot(
            memory,
            currentNodeId="S02",
            taskScore=80,
            resources={"FAST_HORSE": 1},
            tasks=tasks,
            opponent_overrides={"currentNodeId": "S02", "state": "IDLE", "freshness": 84, "goodFruit": 94},
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "CLAIM_TASK", "taskId": "T11_011"}])

    def test_contests_high_value_same_node_task_to_block_below_base_opponent(self):
        memory, context, engine = self.make_engine()
        tasks = [
            {"taskId": "DONE_SELF_1", "nodeId": "S04", "score": 30, "completed": True, "ownerPlayerId": 1001},
            {"taskId": "DONE_SELF_2", "nodeId": "S05", "score": 30, "completed": True, "ownerPlayerId": 1001},
            {"taskId": "DONE_SELF_3", "nodeId": "S09", "score": 30, "completed": True, "ownerPlayerId": 1001},
            {"taskId": "DONE_OPP_1", "nodeId": "S04", "score": 30, "completed": True, "ownerPlayerId": 2002},
            {"taskId": "DONE_OPP_2", "nodeId": "S10", "score": 30, "completed": True, "ownerPlayerId": 2002},
            {"taskId": "T11_011", "nodeId": "S02", "score": 30, "processRound": 4, "active": True},
            {"taskId": "T14_014", "nodeId": "S02", "score": 15, "processRound": 5, "active": True},
        ]

        snap = snapshot(
            memory,
            currentNodeId="S02",
            taskScore=80,
            tasks=tasks,
            opponent_overrides={
                "currentNodeId": "S02",
                "state": "IDLE",
                "freshness": 84,
                "goodFruit": 94,
                "taskScore": 60,
            },
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "CLAIM_TASK", "taskId": "T11_011"}])

    def test_avoids_high_value_same_node_task_when_opponent_also_at_base(self):
        memory, context, engine = self.make_engine()
        tasks = [
            {"taskId": "DONE_SELF_1", "nodeId": "S04", "score": 30, "completed": True, "ownerPlayerId": 1001},
            {"taskId": "DONE_SELF_2", "nodeId": "S05", "score": 30, "completed": True, "ownerPlayerId": 1001},
            {"taskId": "DONE_SELF_3", "nodeId": "S09", "score": 30, "completed": True, "ownerPlayerId": 1001},
            {"taskId": "DONE_OPP_1", "nodeId": "S04", "score": 30, "completed": True, "ownerPlayerId": 2002},
            {"taskId": "DONE_OPP_2", "nodeId": "S10", "score": 30, "completed": True, "ownerPlayerId": 2002},
            {"taskId": "DONE_OPP_3", "nodeId": "S11", "score": 30, "completed": True, "ownerPlayerId": 2002},
            {"taskId": "T11_011", "nodeId": "S02", "score": 30, "processRound": 4, "active": True},
            {"taskId": "T14_014", "nodeId": "S02", "score": 15, "processRound": 5, "active": True},
        ]

        snap = snapshot(
            memory,
            currentNodeId="S02",
            taskScore=80,
            tasks=tasks,
            opponent_overrides={
                "currentNodeId": "S02",
                "state": "IDLE",
                "freshness": 84,
                "goodFruit": 94,
                "taskScore": 90,
            },
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "CLAIM_TASK", "taskId": "T14_014"}])

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

    def test_claims_current_horse_resource_before_process_against_busy_opponent(self):
        start = {
            "matchId": "m1",
            "round": 1,
            "durationRound": 600,
            "players": [{"playerId": 1001, "teamId": "RED"}, {"playerId": 2002, "teamId": "BLUE"}],
            "map": {"gameplay": {"roles": {"startNodeId": "S01", "gateNodeId": "S14", "terminalNodeIds": ["S15"]}}},
            "nodes": [
                {"nodeId": "S04", "processType": "BOARD", "processRound": 7},
                {"nodeId": "S05"},
                {"nodeId": "S14"},
                {"nodeId": "S15", "terminal": True},
            ],
            "edges": [
                {"edgeId": "E1", "fromNodeId": "S04", "toNodeId": "S05", "routeType": "WATER", "distance": 44},
                {"edgeId": "E2", "fromNodeId": "S05", "toNodeId": "S14", "routeType": "ROAD", "distance": 1},
                {"edgeId": "E3", "fromNodeId": "S14", "toNodeId": "S15", "routeType": "ROAD", "distance": 1},
            ],
            "taskTemplates": [{"taskTemplateId": "T06", "requiredResourceTypes": ["FAST_HORSE"]}],
        }
        memory = GameMemory(1001)
        context = memory.apply_start(start)
        engine = DecisionEngine(memory)
        nodes = [
            {"nodeId": "S04", "processType": "BOARD", "processRound": 7, "resourceStock": {"SHORT_HORSE": 1}},
            {"nodeId": "S05"},
            {"nodeId": "S14"},
            {"nodeId": "S15", "terminal": True},
        ]
        tasks = [
            {"taskId": "T06_007", "taskTemplateId": "T06", "nodeId": "S04", "score": 30, "active": True},
            {"taskId": "T08_009", "nodeId": "S05", "score": 30, "processRound": 4, "active": True},
        ]

        snap = snapshot(
            memory,
            currentNodeId="S04",
            nodes=nodes,
            tasks=tasks,
            opponent_overrides={"currentNodeId": "S04", "state": "PROCESSING"},
        )

        self.assertEqual(
            engine.decide(context, snap),
            [{"action": "CLAIM_RESOURCE", "targetNodeId": "S04", "resourceType": "SHORT_HORSE"}],
        )
        self.assertIn("claim required resource SHORT_HORSE", engine.last_reason)

    def test_does_not_claim_current_horse_resource_opponent_processing_same_resource(self):
        memory, context, engine = self.make_engine()
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S02", "processType": "BOARD", "processRound": 3, "resourceStock": {"SHORT_HORSE": 1}},
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
                opponent_overrides={
                    "currentNodeId": "S02",
                    "state": "PROCESSING",
                    "currentProcess": {
                        "action": "CLAIM_RESOURCE",
                        "resourceType": "SHORT_HORSE",
                        "targetNodeId": "S02",
                    },
                },
            ),
        )

        self.assertNotEqual(action, [{"action": "CLAIM_RESOURCE", "targetNodeId": "S02", "resourceType": "SHORT_HORSE"}])

    def test_defers_current_horse_resource_for_downstream_task_race(self):
        start = {
            "matchId": "m1",
            "round": 1,
            "durationRound": 600,
            "players": [{"playerId": 1001, "teamId": "RED"}, {"playerId": 2002, "teamId": "BLUE"}],
            "map": {"gameplay": {"roles": {"startNodeId": "S01", "gateNodeId": "S14", "terminalNodeIds": ["S15"]}}},
            "nodes": [
                {"nodeId": "S09"},
                {"nodeId": "S10"},
                {"nodeId": "S14"},
                {"nodeId": "S15", "terminal": True},
            ],
            "edges": [
                {"edgeId": "E1", "fromNodeId": "S09", "toNodeId": "S10", "routeType": "ROAD", "distance": 40},
                {"edgeId": "E2", "fromNodeId": "S10", "toNodeId": "S14", "routeType": "ROAD", "distance": 1},
                {"edgeId": "E3", "fromNodeId": "S14", "toNodeId": "S15", "routeType": "ROAD", "distance": 1},
            ],
            "taskTemplates": [{"taskTemplateId": "T06", "requiredResourceTypes": ["FAST_HORSE"]}],
        }
        memory = GameMemory(1001)
        context = memory.apply_start(start)
        engine = DecisionEngine(memory)
        nodes = [
            {"nodeId": "S09", "resourceStock": {"FAST_HORSE": 1}},
            {"nodeId": "S10"},
            {"nodeId": "S14"},
            {"nodeId": "S15", "terminal": True},
        ]
        tasks = [
            {"taskId": "T06_006", "taskTemplateId": "T06", "nodeId": "S09", "score": 30, "active": True},
            {"taskId": "T02_003", "nodeId": "S10", "score": 30, "processRound": 4, "active": True},
        ]

        snap = snapshot(
            memory,
            currentNodeId="S09",
            nodes=nodes,
            tasks=tasks,
            opponent_overrides={"currentNodeId": "S05", "nextNodeId": "S09", "state": "MOVING"},
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "MOVE", "targetNodeId": "S10"}])
        self.assertIn("toward S10", engine.last_reason)

    def test_keeps_current_horse_resource_without_opponent_route_pressure(self):
        memory, context, engine = self.make_engine()
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S02", "resourceStock": {"FAST_HORSE": 1}},
            {"nodeId": "S14"},
            {"nodeId": "S15", "terminal": True},
        ]
        tasks = [
            {"taskId": "T06_006", "taskTemplateId": "T06", "nodeId": "S02", "score": 30, "active": True},
            {"taskId": "T02_003", "nodeId": "S14", "score": 30, "active": True},
        ]

        self.assertEqual(
            engine.decide(
                context,
                snapshot(
                    memory,
                    currentNodeId="S02",
                    nodes=nodes,
                    tasks=tasks,
                    opponent_overrides={"currentNodeId": "S09", "state": "IDLE"},
                ),
            ),
            [{"action": "CLAIM_RESOURCE", "targetNodeId": "S02", "resourceType": "FAST_HORSE"}],
        )
        self.assertIn("claim required horse resource FAST_HORSE", engine.last_reason)

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

    def test_required_current_resource_before_process_contests_low_base_current_t06_horse(self):
        start = {
            "matchId": "m1",
            "round": 1,
            "durationRound": 600,
            "players": [{"playerId": 1001, "teamId": "RED"}, {"playerId": 2002, "teamId": "BLUE"}],
            "map": {"gameplay": {"roles": {"startNodeId": "S01", "gateNodeId": "S14", "terminalNodeIds": ["S15"]}}},
            "nodes": [
                {"nodeId": "S01", "start": True},
                {"nodeId": "S04"},
                {"nodeId": "S14", "processRound": 6},
                {"nodeId": "S15", "terminal": True},
            ],
            "edges": [
                {"edgeId": "E1", "fromNodeId": "S04", "toNodeId": "S14", "routeType": "ROAD", "distance": 1},
                {"edgeId": "E2", "fromNodeId": "S14", "toNodeId": "S15", "routeType": "ROAD", "distance": 1},
            ],
            "taskTemplates": [{"taskTemplateId": "T06", "requiredResourceTypes": ["FAST_HORSE"]}],
        }
        memory = GameMemory(1001)
        context = memory.apply_start(start)
        engine = DecisionEngine(memory)
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S04", "processType": "BOARD", "processRound": 7, "resourceStock": {"SHORT_HORSE": 1}},
            {"nodeId": "S14", "processRound": 6},
            {"nodeId": "S15", "terminal": True},
        ]
        tasks = [
            {
                "taskId": "T06_007",
                "taskTemplateId": "T06",
                "nodeId": "S04",
                "score": 30,
                "processRound": 3,
                "active": True,
            },
            {
                "taskId": "T08_008",
                "taskTemplateId": "T08",
                "nodeId": "S04",
                "score": 30,
                "active": False,
                "completed": True,
                "ownerPlayerId": 1001,
            },
        ]

        action = engine.decide(
            context,
            snapshot(
                memory,
                currentNodeId="S04",
                taskScore=30,
                nodes=nodes,
                tasks=tasks,
                opponent_overrides={"currentNodeId": "S04", "state": "IDLE"},
            ),
        )

        self.assertEqual(action, [{"action": "CLAIM_RESOURCE", "targetNodeId": "S04", "resourceType": "SHORT_HORSE"}])
        self.assertIn("contest required horse resource SHORT_HORSE", engine.last_reason)

    def test_required_current_resource_before_process_avoids_idle_opponent_contest_after_base_score(self):
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
                taskScore=90,
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
            opponent_overrides={
                "playerId": 2002,
                "currentNodeId": "S02",
                "state": "PROCESSING",
                "currentProcess": {
                    "action": "PROCESS",
                    "objectKey": "PROCESS:S02:TRANSFER",
                    "targetNodeId": "S02",
                },
            },
        )
        self.assertEqual(engine.decide(context, snap), [])
        self.assertIn("wait for opponent 2002", engine.last_reason)

    def test_does_not_wait_for_opponent_claiming_task_at_fixed_process_node(self):
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
            {"taskId": "T12_012", "nodeId": "S02", "score": 15, "active": False, "ownerPlayerId": 2002},
        ]
        snap = snapshot(
            memory,
            currentNodeId="S02",
            taskScore=80,
            nodes=nodes,
            tasks=tasks,
            opponent_overrides={
                "playerId": 2002,
                "currentNodeId": "S02",
                "state": "PROCESSING",
                "currentProcess": {
                    "action": "CLAIM_TASK",
                    "objectKey": "TASK:T12_012",
                    "targetNodeId": "S02",
                    "taskId": "T12_012",
                },
            },
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "PROCESS", "targetNodeId": "S02"}])
        self.assertNotIn("wait for opponent", engine.last_reason)

    def test_terminal_corridor_process_does_not_idle_yield_after_base_tasks(self):
        start = {
            "matchId": "m1",
            "round": 1,
            "durationRound": 600,
            "players": [{"playerId": 1001, "teamId": "RED"}, {"playerId": 2002, "teamId": "BLUE"}],
            "map": {
                "gameplay": {
                    "roles": {
                        "startNodeId": "S01",
                        "gateNodeId": "S14",
                        "terminalNodeIds": ["S15"],
                        "rushExcludedNodeIds": ["S13"],
                    }
                }
            },
            "nodes": [
                {"nodeId": "S01", "start": True},
                {"nodeId": "S13", "processType": "PALACE_TRANSFER", "processRound": 5},
                {"nodeId": "S14", "processRound": 6},
                {"nodeId": "S15", "terminal": True},
            ],
            "edges": [
                {"edgeId": "E1", "fromNodeId": "S13", "toNodeId": "S14", "routeType": "ROAD", "distance": 18},
                {"edgeId": "E2", "fromNodeId": "S14", "toNodeId": "S15", "routeType": "ROAD", "distance": 10},
            ],
        }
        memory = GameMemory(1001)
        context = memory.apply_start(start)
        engine = DecisionEngine(memory)
        tasks = [
            {"taskId": "DONE_1", "nodeId": "S04", "score": 30, "completed": True, "ownerPlayerId": 1001},
            {"taskId": "DONE_2", "nodeId": "S09", "score": 30, "completed": True, "ownerPlayerId": 1001},
            {"taskId": "DONE_3", "nodeId": "S10", "score": 30, "completed": True, "ownerPlayerId": 1001},
            {"taskId": "T13_013", "nodeId": "S13", "score": 15, "active": False, "completed": True, "ownerPlayerId": 2002},
        ]

        snap = snapshot(
            memory,
            currentNodeId="S13",
            taskScore=80,
            nodes=start["nodes"],
            tasks=tasks,
            round_no=418,
            opponent_overrides={"playerId": 2002, "currentNodeId": "S13", "state": "IDLE", "taskScore": 80},
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "PROCESS", "targetNodeId": "S13"}])
        self.assertNotIn("yield process node", engine.last_reason)

    def test_terminal_corridor_process_can_yield_before_base_tasks(self):
        start = {
            "matchId": "m1",
            "round": 1,
            "durationRound": 600,
            "players": [{"playerId": 1001, "teamId": "RED"}, {"playerId": 2002, "teamId": "BLUE"}],
            "map": {
                "gameplay": {
                    "roles": {
                        "startNodeId": "S01",
                        "gateNodeId": "S14",
                        "terminalNodeIds": ["S15"],
                        "rushExcludedNodeIds": ["S13"],
                    }
                }
            },
            "nodes": [
                {"nodeId": "S01", "start": True},
                {"nodeId": "S13", "processType": "PALACE_TRANSFER", "processRound": 5},
                {"nodeId": "S14", "processRound": 6},
                {"nodeId": "S15", "terminal": True},
            ],
            "edges": [
                {"edgeId": "E1", "fromNodeId": "S13", "toNodeId": "S14", "routeType": "ROAD", "distance": 18},
                {"edgeId": "E2", "fromNodeId": "S14", "toNodeId": "S15", "routeType": "ROAD", "distance": 10},
            ],
        }
        memory = GameMemory(1001)
        context = memory.apply_start(start)
        engine = DecisionEngine(memory)
        tasks = [
            {"taskId": "DONE_1", "nodeId": "S04", "score": 30, "completed": True, "ownerPlayerId": 1001},
            {"taskId": "DONE_2", "nodeId": "S09", "score": 30, "completed": True, "ownerPlayerId": 1001},
            {"taskId": "T13_013", "nodeId": "S13", "score": 15, "active": False, "completed": True, "ownerPlayerId": 2002},
        ]

        snap = snapshot(
            memory,
            currentNodeId="S13",
            taskScore=60,
            nodes=start["nodes"],
            tasks=tasks,
            round_no=418,
            opponent_overrides={"playerId": 2002, "currentNodeId": "S13", "state": "IDLE", "taskScore": 80},
        )

        self.assertEqual(engine.decide(context, snap), [])
        self.assertIn("yield process node S13", engine.last_reason)

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

    def test_drawn_terminal_corridor_process_yields_two_frames_before_retry(self):
        start = {
            "matchId": "m1",
            "round": 1,
            "durationRound": 600,
            "players": [{"playerId": 1001, "teamId": "RED"}, {"playerId": 2002, "teamId": "BLUE"}],
            "map": {
                "gameplay": {
                    "roles": {
                        "startNodeId": "S01",
                        "gateNodeId": "S14",
                        "terminalNodeIds": ["S15"],
                        "rushExcludedNodeIds": ["S13"],
                    }
                }
            },
            "nodes": [
                {"nodeId": "S01", "start": True},
                {"nodeId": "S13", "processType": "PALACE_TRANSFER", "processRound": 5},
                {"nodeId": "S14", "processRound": 6},
                {"nodeId": "S15", "terminal": True},
            ],
            "edges": [
                {"edgeId": "E1", "fromNodeId": "S13", "toNodeId": "S14", "routeType": "ROAD", "distance": 18},
                {"edgeId": "E2", "fromNodeId": "S14", "toNodeId": "S15", "routeType": "ROAD", "distance": 10},
            ],
        }
        memory = GameMemory(1001)
        context = memory.apply_start(start)
        engine = DecisionEngine(memory)
        memory.skipped_process_nodes.add("S13")
        tasks = [
            {"taskId": "DONE_1", "nodeId": "S04", "score": 30, "completed": True, "ownerPlayerId": 1001},
            {"taskId": "DONE_2", "nodeId": "S05", "score": 30, "completed": True, "ownerPlayerId": 1001},
            {"taskId": "DONE_3", "nodeId": "S09", "score": 30, "completed": True, "ownerPlayerId": 1001},
            {"taskId": "DONE_4", "nodeId": "S10", "score": 30, "completed": True, "ownerPlayerId": 1001},
        ]

        first_yield = snapshot(
            memory,
            currentNodeId="S13",
            nodes=start["nodes"],
            tasks=tasks,
            opponent_overrides={"playerId": 2002, "currentNodeId": "S13", "state": "IDLE"},
            round_no=414,
        )
        self.assertEqual(engine.decide(context, first_yield), [])
        self.assertEqual(memory.drawn_process_yield_counts["S13"], 1)

        second_yield = snapshot(
            memory,
            currentNodeId="S13",
            nodes=start["nodes"],
            tasks=tasks,
            opponent_overrides={"playerId": 2002, "currentNodeId": "S13", "state": "IDLE"},
            round_no=415,
        )
        self.assertEqual(engine.decide(context, second_yield), [])
        self.assertEqual(memory.drawn_process_yield_counts["S13"], 2)

        retry = snapshot(
            memory,
            currentNodeId="S13",
            nodes=start["nodes"],
            tasks=tasks,
            opponent_overrides={"playerId": 2002, "currentNodeId": "S13", "state": "IDLE"},
            round_no=416,
        )
        self.assertEqual(engine.decide(context, retry), [{"action": "PROCESS", "targetNodeId": "S13"}])

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

    def test_drawn_high_value_task_retries_once_when_low_value_fallback_concedes_opponent_base(self):
        memory, context, engine = self.make_engine()
        tasks = [
            {"taskId": "DONE_SELF_1", "nodeId": "S04", "score": 30, "completed": True, "ownerPlayerId": 1001},
            {"taskId": "DONE_SELF_2", "nodeId": "S05", "score": 30, "completed": True, "ownerPlayerId": 1001},
            {"taskId": "DONE_SELF_3", "nodeId": "S09", "score": 30, "completed": True, "ownerPlayerId": 1001},
            {"taskId": "DONE_OPP_1", "nodeId": "S04", "score": 30, "completed": True, "ownerPlayerId": 2002},
            {"taskId": "DONE_OPP_2", "nodeId": "S10", "score": 30, "completed": True, "ownerPlayerId": 2002},
            {"taskId": "T11_011", "nodeId": "S02", "score": 30, "processRound": 4, "active": True},
            {"taskId": "T14_014", "nodeId": "S02", "score": 15, "processRound": 5, "active": True},
        ]
        memory.skipped_task_claims.add("T11_011")

        snap = snapshot(
            memory,
            currentNodeId="S02",
            tasks=tasks,
            opponent_overrides={"currentNodeId": "S02", "state": "IDLE", "taskScore": 60},
            round_no=284,
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "CLAIM_TASK", "taskId": "T11_011"}])
        self.assertEqual(memory.drawn_task_retry_counts["T11_011"], 1)
        self.assertNotIn("T11_011", memory.skipped_task_claims)

    def test_drawn_high_value_task_retry_limit_falls_back_to_low_value_task(self):
        memory, context, engine = self.make_engine()
        tasks = [
            {"taskId": "DONE_SELF_1", "nodeId": "S04", "score": 30, "completed": True, "ownerPlayerId": 1001},
            {"taskId": "DONE_SELF_2", "nodeId": "S05", "score": 30, "completed": True, "ownerPlayerId": 1001},
            {"taskId": "DONE_SELF_3", "nodeId": "S09", "score": 30, "completed": True, "ownerPlayerId": 1001},
            {"taskId": "DONE_OPP_1", "nodeId": "S04", "score": 30, "completed": True, "ownerPlayerId": 2002},
            {"taskId": "DONE_OPP_2", "nodeId": "S10", "score": 30, "completed": True, "ownerPlayerId": 2002},
            {"taskId": "T11_011", "nodeId": "S02", "score": 30, "processRound": 4, "active": True},
            {"taskId": "T14_014", "nodeId": "S02", "score": 15, "processRound": 5, "active": True},
        ]
        memory.skipped_task_claims.add("T11_011")
        memory.drawn_task_retry_counts["T11_011"] = 1

        snap = snapshot(
            memory,
            currentNodeId="S02",
            tasks=tasks,
            opponent_overrides={"currentNodeId": "S02", "state": "IDLE", "taskScore": 60},
            round_no=284,
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "CLAIM_TASK", "taskId": "T14_014"}])
        self.assertIn("T11_011", memory.skipped_task_claims)

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

    def test_endgame_uses_ice_box_before_moving(self):
        memory, context, engine = self.make_engine()
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S13"},
            {"nodeId": "S14", "processRound": 6},
            {"nodeId": "S15", "terminal": True},
        ]
        snap = snapshot(
            memory,
            currentNodeId="S13",
            resources={"ICE_BOX": 2},
            freshness=74.7,
            nodes=nodes,
            round_no=436,
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "USE_RESOURCE", "resourceType": "ICE_BOX"}])
        self.assertIn("use ICE_BOX", engine.last_reason)

    def test_endgame_does_not_waste_ice_box_when_freshness_is_high(self):
        memory, context, engine = self.make_engine()
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S13"},
            {"nodeId": "S14", "processRound": 6},
            {"nodeId": "S15", "terminal": True},
        ]
        snap = snapshot(
            memory,
            currentNodeId="S13",
            resources={"ICE_BOX": 1},
            freshness=95,
            nodes=nodes,
            round_no=436,
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "MOVE", "targetNodeId": "S14"}])

    def test_moving_with_ice_box_continues_to_next_node(self):
        memory, context, engine = self.make_engine()
        snap = snapshot(
            memory,
            state="MOVING",
            currentNodeId="S13",
            nextNodeId="S14",
            resources={"ICE_BOX": 1},
            freshness=70,
            round_no=436,
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "MOVE", "targetNodeId": "S14"}])

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

    def test_sets_guard_on_key_route_after_base_task_score(self):
        memory, context, engine = self.make_engine()
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S02", "nodeType": "KEY_PASS"},
            {"nodeId": "S14"},
            {"nodeId": "S15", "terminal": True},
        ]
        snap = snapshot(
            memory,
            currentNodeId="S02",
            taskScore=90,
            goodFruit=80,
            nodes=nodes,
            opponent_overrides={"currentNodeId": "S01", "state": "IDLE"},
        )
        self.assertEqual(
            engine.decide(context, snap),
            [{"action": "SET_GUARD", "targetNodeId": "S02", "extraGoodFruit": 1}],
        )

    def test_does_not_set_third_active_guard(self):
        memory, context, engine = self.make_engine()
        nodes = [
            {"nodeId": "S01", "start": True},
            {"nodeId": "S02", "nodeType": "KEY_PASS"},
            {"nodeId": "S07", "guard": {"ownerTeamId": "RED", "defense": 4, "active": True}},
            {"nodeId": "S09", "guard": {"ownerTeamId": "RED", "defense": 4, "active": True}},
            {"nodeId": "S14"},
            {"nodeId": "S15", "terminal": True},
        ]
        snap = snapshot(
            memory,
            currentNodeId="S02",
            taskScore=90,
            goodFruit=80,
            nodes=nodes,
            opponent_overrides={"currentNodeId": "S01", "state": "IDLE"},
        )
        self.assertEqual(engine.decide(context, snap), [{"action": "MOVE", "targetNodeId": "S14"}])

    def test_squad_scouts_high_value_remote_task(self):
        memory, context, engine = self.make_engine()
        tasks = [{"taskId": "T01_1", "nodeId": "S02", "score": 30, "processRound": 6, "active": True}]
        snap = snapshot(memory, currentNodeId="S01", squadAvailable=1, tasks=tasks)
        self.assertEqual(
            engine.decide(context, snap),
            [{"action": "MOVE", "targetNodeId": "S02"}, {"action": "SQUAD_SCOUT", "targetNodeId": "S02"}],
        )

    def test_action_result_error_updates_recovery_memory(self):
        memory, context, engine = self.make_engine()
        result = {
            "playerId": 1001,
            "action": "CLAIM_TASK",
            "accepted": False,
            "taskId": "T01_1",
            "errorCode": "TASK_EXPIRED",
        }
        snap = snapshot(memory, action_results=[result])
        self.assertEqual(memory.error_counts["TASK_EXPIRED"], 1)
        self.assertEqual(memory.last_error_policy, "skip_task")
        self.assertIn("T01_1", memory.skipped_task_claims)
        self.assertEqual(engine.decide(context, snap), [{"action": "MOVE", "targetNodeId": "S02"}])

    def test_contesting_state_only_sends_task_window_card(self):
        memory, context, engine = self.make_engine()
        contests = [{"contestId": "C1", "contestType": "TASK", "redPlayerId": 1001, "bluePlayerId": 2002, "roundIndex": 1}]
        snap = snapshot(memory, state="CONTESTING", currentNodeId="S02", contests=contests)
        self.assertEqual(engine.decide(context, snap), [{"action": "WINDOW_CARD", "contestId": "C1", "card": "XIAN_GONG"}])

    def test_window_participation_can_be_read_from_source_action_mapping(self):
        memory, context, engine = self.make_engine()
        contests = [
            {
                "contestId": "C1",
                "contestType": "TASK",
                "sourceActionTypes": {"1001": "CLAIM_TASK", "2002": "CLAIM_TASK"},
                "roundIndex": 1,
            }
        ]
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

    def test_fixed_process_window_uses_bing_zheng_when_xian_gong_is_not_safe(self):
        memory, context, engine = self.make_engine()
        contests = [
            {
                "contestId": "C1",
                "contestType": "DOCK",
                "targetNodeId": "S13",
                "redPlayerId": 1001,
                "bluePlayerId": 2002,
                "objectKey": "PROCESS:S13:PALACE_TRANSFER",
                "sourceActionTypes": {"1001": "PROCESS", "2002": "PROCESS"},
                "roundIndex": 2,
            }
        ]
        snap = snapshot(
            memory,
            state="CONTESTING",
            currentNodeId="S13",
            freshness=77,
            goodFruit=95,
            guardActionPoint=4,
            contests=contests,
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "WINDOW_CARD", "contestId": "C1", "card": "BING_ZHENG"}])

    def test_fixed_process_window_abstains_without_bing_zheng_budget(self):
        memory, context, engine = self.make_engine()
        contests = [
            {
                "contestId": "C1",
                "contestType": "DOCK",
                "targetNodeId": "S13",
                "redPlayerId": 1001,
                "bluePlayerId": 2002,
                "objectKey": "PROCESS:S13:PALACE_TRANSFER",
                "sourceActionTypes": {"1001": "PROCESS", "2002": "PROCESS"},
            }
        ]
        snap = snapshot(
            memory,
            state="CONTESTING",
            currentNodeId="S13",
            freshness=77,
            goodFruit=95,
            guardActionPoint=0,
            contests=contests,
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "WINDOW_CARD", "contestId": "C1", "card": "ABSTAIN"}])

    def test_fixed_process_window_repeats_same_bing_zheng_tie_without_counter(self):
        memory, context, engine = self.make_engine()
        contests = [
            {
                "contestId": "C1",
                "contestType": "DOCK",
                "targetNodeId": "S13",
                "redPlayerId": 1001,
                "bluePlayerId": 2002,
                "objectKey": "PROCESS:S13:PALACE_TRANSFER",
                "sourceActionTypes": {"1001": "PROCESS", "2002": "PROCESS"},
                "roundIndex": 2,
                "cards": {"R1:RED": "BING_ZHENG", "R1:BLUE": "BING_ZHENG"},
            }
        ]
        snap = snapshot(
            memory,
            state="CONTESTING",
            currentNodeId="S13",
            freshness=77,
            goodFruit=95,
            guardActionPoint=3,
            contests=contests,
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "WINDOW_CARD", "contestId": "C1", "card": "BING_ZHENG"}])

    def test_fixed_process_window_repeats_same_xian_gong_tie_without_counter(self):
        memory, context, engine = self.make_engine()
        contests = [
            {
                "contestId": "C1",
                "contestType": "DOCK",
                "targetNodeId": "S02",
                "redPlayerId": 1001,
                "bluePlayerId": 2002,
                "objectKey": "PROCESS:S02:TRANSFER",
                "sourceActionTypes": {"1001": "PROCESS", "2002": "PROCESS"},
                "roundIndex": 2,
                "cards": {"R1:RED": "XIAN_GONG", "R1:BLUE": "XIAN_GONG"},
            }
        ]
        snap = snapshot(
            memory,
            state="CONTESTING",
            currentNodeId="S02",
            freshness=97,
            goodFruit=99,
            guardActionPoint=4,
            contests=contests,
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "WINDOW_CARD", "contestId": "C1", "card": "XIAN_GONG"}])

    def test_fixed_process_window_counters_same_bing_zheng_tie_with_xian_gong(self):
        memory, context, engine = self.make_engine()
        contests = [
            {
                "contestId": "C1",
                "contestType": "DOCK",
                "targetNodeId": "S13",
                "redPlayerId": 1001,
                "bluePlayerId": 2002,
                "objectKey": "PROCESS:S13:PALACE_TRANSFER",
                "sourceActionTypes": {"1001": "PROCESS", "2002": "PROCESS"},
                "roundIndex": 2,
                "cards": {"R1:RED": "BING_ZHENG", "R1:BLUE": "BING_ZHENG"},
            }
        ]
        snap = snapshot(
            memory,
            state="CONTESTING",
            currentNodeId="S13",
            freshness=85,
            goodFruit=95,
            guardActionPoint=3,
            contests=contests,
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "WINDOW_CARD", "contestId": "C1", "card": "XIAN_GONG"}])

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

    def test_task_window_same_xian_gong_tie_preserves_only_horse_resource_for_t06(self):
        memory, context, engine = self.make_engine()
        contests = [
            {
                "contestId": "C1",
                "contestType": "TASK",
                "taskId": "T06_006",
                "redPlayerId": 1001,
                "bluePlayerId": 2002,
                "roundIndex": 2,
                "cards": {"R1:RED": "XIAN_GONG", "R1:BLUE": "XIAN_GONG"},
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

        self.assertEqual(engine.decide(context, snap), [{"action": "WINDOW_CARD", "contestId": "C1", "card": "ABSTAIN"}])

    def test_task_window_same_xian_gong_tie_uses_free_qiang_xing_with_horse_buff(self):
        memory, context, engine = self.make_engine()
        contests = [
            {
                "contestId": "C1",
                "contestType": "TASK",
                "taskId": "T06_006",
                "redPlayerId": 1001,
                "bluePlayerId": 2002,
                "roundIndex": 2,
                "cards": {"R1:RED": "XIAN_GONG", "R1:BLUE": "XIAN_GONG"},
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
            buffs=[{"type": "FAST_HORSE"}],
            tasks=tasks,
            contests=contests,
        )

        self.assertEqual(engine.decide(context, snap), [{"action": "WINDOW_CARD", "contestId": "C1", "card": "QIANG_XING"}])

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
