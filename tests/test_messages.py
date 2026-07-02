from __future__ import annotations

import unittest

from litchi_bot.protocol.messages import action, ready, registration


class MessageTests(unittest.TestCase):
    def test_registration_message(self) -> None:
        message = registration("1001", "demo", "0.1")

        self.assertEqual(message["msg_name"], "registration")
        self.assertEqual(message["msg_data"]["playerId"], 1001)
        self.assertEqual(message["msg_data"]["playerName"], "demo")
        self.assertEqual(message["msg_data"]["version"], "0.1")

    def test_ready_message(self) -> None:
        message = ready("match_1", 1, 1001)

        self.assertEqual(
            message,
            {
                "msg_name": "ready",
                "msg_data": {"matchId": "match_1", "round": 1, "playerId": 1001},
            },
        )

    def test_action_message_defaults_to_empty_actions(self) -> None:
        message = action("match_1", 12, "1001")

        self.assertEqual(message["msg_name"], "action")
        self.assertEqual(message["msg_data"]["matchId"], "match_1")
        self.assertEqual(message["msg_data"]["round"], 12)
        self.assertEqual(message["msg_data"]["playerId"], 1001)
        self.assertEqual(message["msg_data"]["actions"], [])


if __name__ == "__main__":
    unittest.main()
