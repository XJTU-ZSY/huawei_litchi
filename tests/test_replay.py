import unittest

from litchi_bot.replay import analyze_messages


class ReplayAnalysisTest(unittest.TestCase):
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
