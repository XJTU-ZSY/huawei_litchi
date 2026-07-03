import unittest

from litchi_bot.replay import analyze_messages, format_report


class ReplayAnalysisTest(unittest.TestCase):
    def test_extracts_replay_timelines(self):
        messages = [
            {
                "msg_name": "inquire",
                "msg_data": {
                    "round": 2,
                    "players": [{"playerId": 1001}],
                    "actionResults": [
                        {"round": 1, "playerId": 1001, "action": "MOVE", "accepted": True},
                        {"round": 1, "playerId": 1002, "action": "WAIT", "accepted": True},
                    ],
                    "events": [
                        {
                            "type": "NODE_ENTER",
                            "round": 1,
                            "payload": {"playerId": 1001, "fromNodeId": "S01", "nodeId": "S02"},
                        },
                        {
                            "type": "TASK_COMPLETE",
                            "round": 2,
                            "payload": {
                                "playerId": 1001,
                                "taskId": "T01_001",
                                "taskTemplateId": "T01",
                                "nodeId": "S02",
                                "score": 30,
                            },
                        },
                        {
                            "type": "RESOURCE_CLAIM",
                            "round": 2,
                            "payload": {"playerId": 1001, "nodeId": "S02", "resourceType": "FAST_HORSE"},
                        },
                        {
                            "type": "WINDOW_CARD_REVEAL",
                            "round": 2,
                            "payload": {
                                "contestId": "C1",
                                "roundIndex": 1,
                                "redCard": "XIAN_GONG",
                                "blueCard": "ABSTAIN",
                                "redPoint": 1,
                                "bluePoint": 0,
                            },
                        },
                    ],
                },
            }
        ]

        summary = analyze_messages(messages, player_id=1001)

        self.assertEqual(summary["actionCounts"]["1001"], {"MOVE": 1})
        self.assertEqual(summary["actionCounts"]["1002"], {"WAIT": 1})
        self.assertEqual(
            summary["routes"]["1001"],
            [{"round": 1, "fromNodeId": "S01", "nodeId": "S02", "routeEdgeId": None}],
        )
        self.assertEqual(summary["taskCompletions"]["1001"][0]["taskId"], "T01_001")
        self.assertEqual(summary["resourceEvents"]["1001"][0]["resourceType"], "FAST_HORSE")
        self.assertEqual(summary["windowReveals"][0]["blueCard"], "ABSTAIN")

        report = format_report(summary)

        self.assertIn("action counts: {'1001': {'MOVE': 1}, '1002': {'WAIT': 1}}", report)
        self.assertIn("S01->S02@1", report)
        self.assertIn("T01_001:S02:score=30:@2", report)
        self.assertIn("RESOURCE_CLAIM:FAST_HORSE:S02:@2", report)
        self.assertIn("C1 roundIndex=1 red=XIAN_GONG blue=ABSTAIN points=1-0 @2", report)

    def test_infers_delivery_from_final_player_state(self):
        messages = [
            {
                "msg_name": "inquire",
                "msg_data": {
                    "round": 457,
                    "players": [
                        {
                            "playerId": 1001,
                            "delivered": False,
                            "goodFruit": 95,
                            "freshness": 75.01,
                        }
                    ],
                },
            },
            {
                "msg_name": "over",
                "msg_data": {
                    "players": [
                        {
                            "playerId": 1001,
                            "delivered": True,
                            "goodFruit": 95,
                            "freshness": 75.01,
                            "totalScore": 742,
                        }
                    ]
                },
            },
        ]

        summary = analyze_messages(messages, player_id=1001)

        self.assertEqual(
            summary["deliveries"]["1001"],
            {
                "round": None,
                "goodFruit": 95,
                "freshness": 75.01,
                "source": "finalPlayer",
                "inferred": True,
            },
        )

    def test_delivery_success_event_takes_precedence_over_final_state(self):
        messages = [
            {
                "msg_name": "inquire",
                "msg_data": {
                    "round": 452,
                    "players": [{"playerId": 1001, "delivered": True, "goodFruit": 94, "freshness": 74.5}],
                    "events": [
                        {
                            "type": "DELIVER_SUCCESS",
                            "round": 451,
                            "payload": {"playerId": 1001, "goodFruit": 95, "freshness": 75.01},
                        }
                    ],
                },
            },
            {
                "msg_name": "over",
                "msg_data": {"players": [{"playerId": 1001, "delivered": True, "goodFruit": 94, "freshness": 74.5}]},
            },
        ]

        summary = analyze_messages(messages, player_id=1001)

        self.assertEqual(summary["deliveries"]["1001"], {"round": 451, "goodFruit": 95, "freshness": 75.01})

    def test_delivery_inference_respects_player_filter(self):
        messages = [
            {
                "msg_name": "over",
                "msg_data": {
                    "players": [
                        {"playerId": 1001, "delivered": False},
                        {"playerId": 1002, "delivered": True, "goodFruit": 97, "freshness": 75.32},
                    ]
                },
            }
        ]

        summary = analyze_messages(messages, player_id=1001)

        self.assertEqual(summary["deliveries"], {})


if __name__ == "__main__":
    unittest.main()
