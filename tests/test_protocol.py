import unittest

from litchi_bot.protocol import action, parse_player_id, ready, registration


class ProtocolTest(unittest.TestCase):
    def test_parse_player_id(self):
        self.assertEqual(parse_player_id("1001"), 1001)
        self.assertEqual(parse_player_id("player1"), "player1")

    def test_registration_message(self):
        message = registration(1001, "team", "v")
        self.assertEqual(message["msg_name"], "registration")
        self.assertEqual(message["msg_data"]["playerId"], 1001)

    def test_ready_message(self):
        message = ready("m1", 1, 1001)
        self.assertEqual(message["msg_name"], "ready")
        self.assertEqual(message["msg_data"]["matchId"], "m1")

    def test_action_message(self):
        message = action("m1", 12, 1001, [{"action": "WAIT"}])
        self.assertEqual(message["msg_data"]["round"], 12)
        self.assertEqual(message["msg_data"]["actions"][0]["action"], "WAIT")


if __name__ == "__main__":
    unittest.main()
