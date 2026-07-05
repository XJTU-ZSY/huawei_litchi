import unittest

from litchi_bot.protocol import ERROR_RECOVERY_POLICIES, action, error_recovery_policy, parse_player_id, ready, registration


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

    def test_protocol_error_policy_covers_documented_codes(self):
        documented_codes = {
            "INVALID_LENGTH_PREFIX",
            "INVALID_JSON",
            "INVALID_ACTION_TYPE",
            "ACTION_REJECTED",
            "MATCH_ID_MISMATCH",
            "ACTION_TOO_LATE",
            "DUPLICATE_ACTION",
            "PLAYER_ADDRESS_MISMATCH",
            "PLAYER_NOT_ALLOWED",
            "MATCH_ALREADY_STARTED",
            "PLAYER_LIMIT_EXCEEDED",
            "INVALID_ACTION_CONFLICT",
            "PARAM_OUT_OF_RANGE",
            "MOVING_ACTION_FORBIDDEN",
            "RESTING_ACTION_FORBIDDEN",
            "SAFE_ZONE_FORBIDDEN",
            "PROCESS_REQUIRED",
            "PROCESS_NOT_AVAILABLE",
            "NOT_AT_TARGET_NODE",
            "MOVE_MISSING_TARGET",
            "MOVE_EDGE_NOT_FOUND",
            "MOVE_BLOCKED_BY_GUARD",
            "TARGET_NOT_FOUND",
            "TARGET_NOT_REACHABLE",
            "RESOURCE_NOT_ENOUGH",
            "RESOURCE_NOT_USABLE",
            "TASK_NOT_FOUND",
            "TASK_PROTECTED",
            "TASK_REQUIREMENT_NOT_MET",
            "TASK_EXPIRED",
            "OBJECT_BUSY",
            "WINDOW_DRAW_RETRY_LIMIT",
            "VERIFY_REQUIRED",
            "ALREADY_VERIFIED",
            "DELIVER_NOT_AT_TERMINAL",
            "DELIVER_NOT_VERIFIED",
            "DELIVER_REQUIREMENT_NOT_MET",
            "ALREADY_DELIVERED",
            "RUSH_TACTIC_INVALID_BINDING",
            "HORSE_BUFF_CONFLICT",
            "FORCED_PASS_REPEAT",
            "OBSTACLE_NOT_FOUND",
        }
        self.assertTrue(documented_codes.issubset(ERROR_RECOVERY_POLICIES))
        self.assertEqual(error_recovery_policy("move_blocked_by_guard"), "handle_blocker")
        self.assertEqual(error_recovery_policy("UNKNOWN_FROM_SERVER"), "business_rejection")


if __name__ == "__main__":
    unittest.main()
