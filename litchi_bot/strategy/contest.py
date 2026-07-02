from __future__ import annotations

from typing import Any

from ..game_state import GameContext, GameSnapshot, same_player_id


class WindowCardSelector:
    def choose(self, context: GameContext, snapshot: GameSnapshot) -> dict[str, Any] | None:
        contest = self._active_contest_for_self(context, snapshot)
        if contest is None:
            return None
        card = self._choose_card(snapshot.self_player, contest)
        return {"action": "WINDOW_CARD", "contestId": contest["contestId"], "card": card}

    def _active_contest_for_self(self, context: GameContext, snapshot: GameSnapshot) -> dict[str, Any] | None:
        for contest in snapshot.contests:
            if contest.get("status") == "SUPPRESSED" or contest.get("resolved") is True:
                continue
            if not contest.get("contestId"):
                continue
            if same_player_id(contest.get("redPlayerId"), context.player_id) or same_player_id(
                contest.get("bluePlayerId"), context.player_id
            ):
                return contest
        return None

    def _choose_card(self, player: dict[str, Any], contest: dict[str, Any]) -> str:
        resources = player.get("resources") or {}
        contest_type = contest.get("contestType")
        if player.get("guardActionPoint", 0) > 0 and contest_type in {"GATE", "TASK", "PASS", "OBSTACLE"}:
            return "BING_ZHENG"
        if resources.get("PASS_TOKEN", 0) + resources.get("OFFICIAL_PERMIT", 0) > 0:
            return "YAN_DIE"
        has_speed = any((buff.get("type") in {"FAST_HORSE", "SHORT_HORSE", "RUSH_SPEED"}) for buff in player.get("buffs") or [])
        if has_speed or resources.get("FAST_HORSE", 0) + resources.get("SHORT_HORSE", 0) > 0:
            return "QIANG_XING"
        if float(player.get("freshness") or 0) >= 80 and int(player.get("goodFruit") or 0) > 30:
            return "XIAN_GONG"
        return "ABSTAIN"
