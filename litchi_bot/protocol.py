from __future__ import annotations

from typing import Any


ERROR_RECOVERY_POLICIES = {
    # Immediate packet errors returned through msg_name:error.
    "INVALID_LENGTH_PREFIX": "fatal_packet",
    "INVALID_JSON": "fatal_packet",
    "MATCH_ID_MISMATCH": "fatal_packet",
    "ACTION_TOO_LATE": "resend_next_round",
    "DUPLICATE_ACTION": "ignore_duplicate",
    "PLAYER_ADDRESS_MISMATCH": "fatal_registration",
    "PLAYER_NOT_ALLOWED": "fatal_registration",
    "MATCH_ALREADY_STARTED": "fatal_registration",
    "PLAYER_LIMIT_EXCEEDED": "fatal_registration",
    # Action format and category errors.
    "INVALID_ACTION_TYPE": "drop_bad_action",
    "ACTION_REJECTED": "business_rejection",
    "INVALID_ACTION_CONFLICT": "drop_conflicting_category",
    "PARAM_OUT_OF_RANGE": "drop_bad_action",
    # State-limit errors.
    "MOVING_ACTION_FORBIDDEN": "wait_for_state",
    "RESTING_ACTION_FORBIDDEN": "wait_for_state",
    "SAFE_ZONE_FORBIDDEN": "drop_zone_forbidden",
    "PROCESS_REQUIRED": "retry_process",
    "PROCESS_NOT_AVAILABLE": "skip_process",
    "NOT_AT_TARGET_NODE": "replan_position",
    # Movement / resource / task / window errors.
    "MOVE_MISSING_TARGET": "replan_position",
    "MOVE_EDGE_NOT_FOUND": "replan_route",
    "MOVE_BLOCKED_BY_GUARD": "handle_blocker",
    "TARGET_NOT_FOUND": "replan_target",
    "TARGET_NOT_REACHABLE": "replan_route",
    "RESOURCE_NOT_ENOUGH": "skip_costly_action",
    "RESOURCE_NOT_USABLE": "skip_costly_action",
    "TASK_NOT_FOUND": "skip_task",
    "TASK_PROTECTED": "skip_task",
    "TASK_REQUIREMENT_NOT_MET": "skip_task",
    "TASK_EXPIRED": "skip_task",
    "OBJECT_BUSY": "skip_object_temporarily",
    "WINDOW_DRAW_RETRY_LIMIT": "skip_object_temporarily",
    # Endgame / tactic / other errors.
    "VERIFY_REQUIRED": "verify_before_delivery",
    "ALREADY_VERIFIED": "skip_verify",
    "DELIVER_NOT_AT_TERMINAL": "go_terminal",
    "DELIVER_NOT_VERIFIED": "verify_before_delivery",
    "DELIVER_REQUIREMENT_NOT_MET": "replan_delivery",
    "ALREADY_DELIVERED": "stop_actions",
    "RUSH_TACTIC_INVALID_BINDING": "drop_bad_tactic",
    "HORSE_BUFF_CONFLICT": "skip_speed_resource",
    "FORCED_PASS_REPEAT": "avoid_forced_pass_target",
    "OBSTACLE_NOT_FOUND": "skip_obstacle",
}


def normalize_error_code(value: Any) -> str:
    return str(value or "").strip().upper()


def error_recovery_policy(error_code: Any) -> str:
    return ERROR_RECOVERY_POLICIES.get(normalize_error_code(error_code), "business_rejection")


def parse_player_id(value: str) -> int | str:
    text = str(value).strip()
    if text.isdigit():
        return int(text)
    return text


def registration(player_id: int | str, player_name: str = "litchi-python", version: str = "0.1.0") -> dict[str, Any]:
    return {
        "msg_name": "registration",
        "msg_data": {
            "playerId": player_id,
            "playerName": player_name,
            "version": version,
        },
    }


def ready(match_id: str, round_no: int, player_id: int | str) -> dict[str, Any]:
    return {
        "msg_name": "ready",
        "msg_data": {
            "matchId": match_id,
            "round": round_no,
            "playerId": player_id,
        },
    }


def action(match_id: str, round_no: int, player_id: int | str, actions: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "msg_name": "action",
        "msg_data": {
            "matchId": match_id,
            "round": round_no,
            "playerId": player_id,
            "actions": actions,
        },
    }
