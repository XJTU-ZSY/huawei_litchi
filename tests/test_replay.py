import unittest

from litchi_bot.replay import analyze_messages


class ReplayAnalysisTest(unittest.TestCase):
    def test_uses_over_players_as_delivery_evidence(self):
        messages = [
            {
                "msg_name": "over",
                "msg_data": {
                    "overRound": 461,
                    "players": [
                        {"playerId": 1001, "delivered": True, "deliverRound": 458, "goodFruit": 92, "freshness": 74.937},
                        {"playerId": 1002, "delivered": True, "deliverRound": 461, "goodFruit": 92, "freshness": 74.721},
                    ],
                },
            }
        ]

        summary = analyze_messages(messages, player_id=1002)

        self.assertEqual(summary["deliveries"], {"1002": {"round": 461, "goodFruit": 92, "freshness": 74.721}})

    def test_deliver_success_event_takes_precedence_over_over_summary(self):
        messages = [
            {
                "msg_name": "inquire",
                "msg_data": {
                    "round": 459,
                    "events": [
                        {
                            "type": "DELIVER_SUCCESS",
                            "round": 459,
                            "payload": {"playerId": 1002, "goodFruit": 93, "freshness": 75.0},
                        }
                    ],
                },
            },
            {
                "msg_name": "over",
                "msg_data": {
                    "overRound": 461,
                    "players": [
                        {"playerId": 1002, "delivered": True, "deliverRound": 461, "goodFruit": 92, "freshness": 74.721}
                    ],
                },
            },
        ]

        summary = analyze_messages(messages, player_id=1002)

        self.assertEqual(summary["deliveries"], {"1002": {"round": 459, "goodFruit": 93, "freshness": 75.0}})


if __name__ == "__main__":
    unittest.main()
