from __future__ import annotations

from typing import Any

from ..game_state import GameContext, GameSnapshot, same_player_id


TASK_CONTEST_TYPES = {"TASK"}
BING_CONTEST_TYPES = {"GATE", "TASK", "PASS", "OBSTACLE"}
SPEED_BUFF_TYPES = {"FAST_HORSE", "SHORT_HORSE", "RUSH_SPEED"}
WINDOW_CARDS = {"YAN_DIE", "QIANG_XING", "XIAN_GONG", "BING_ZHENG", "ABSTAIN"}
COUNTER_CARD_PREFERENCE = {
    "YAN_DIE": ("BING_ZHENG", "XIAN_GONG", "YAN_DIE", "ABSTAIN"),
    "QIANG_XING": ("BING_ZHENG", "YAN_DIE", "QIANG_XING", "ABSTAIN"),
    "XIAN_GONG": ("QIANG_XING", "XIAN_GONG", "ABSTAIN"),
    "BING_ZHENG": ("XIAN_GONG", "BING_ZHENG", "ABSTAIN"),
    "ABSTAIN": ("BING_ZHENG", "XIAN_GONG", "YAN_DIE", "QIANG_XING"),
}


class WindowCardSelector:
    def choose(self, context: GameContext, snapshot: GameSnapshot) -> dict[str, Any] | None:
        contest = self._active_contest_for_self(context, snapshot)
        if contest is None:
            return None
        card = self._choose_card(context, snapshot, contest)
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

    def _choose_card(self, context: GameContext, snapshot: GameSnapshot, contest: dict[str, Any]) -> str:
        contest_type = str(contest.get("contestType") or "").upper()
        player = snapshot.self_player
        affordable = self._affordable_cards(player)

        low_value_card = self._low_value_process_card(context, contest, affordable)
        if low_value_card is not None:
            return low_value_card

        counter = self._counter_latest_opponent_card(context, contest, affordable)
        if counter is not None:
            return counter

        if contest_type in TASK_CONTEST_TYPES and "XIAN_GONG" in affordable:
            return "XIAN_GONG"

        if "BING_ZHENG" in affordable and contest_type in BING_CONTEST_TYPES:
            return "BING_ZHENG"
        if "YAN_DIE" in affordable:
            return "YAN_DIE"
        if "QIANG_XING" in affordable:
            return "QIANG_XING"
        if "XIAN_GONG" in affordable:
            return "XIAN_GONG"
        return "ABSTAIN"

    def _low_value_process_card(
        self, context: GameContext, contest: dict[str, Any], affordable: set[str]
    ) -> str | None:
        if not self._is_fixed_process_contest(context, contest):
            return None
        opponent_card = self._latest_opponent_card(context, contest)
        if opponent_card == "ABSTAIN" and self._self_is_ahead(context, contest):
            return "ABSTAIN"
        if opponent_card == "XIAN_GONG" and "QIANG_XING" not in affordable and self._should_defer_process_after_draw(
            context
        ):
            return "ABSTAIN"
        return None

    def _is_fixed_process_contest(self, context: GameContext, contest: dict[str, Any]) -> bool:
        if str(contest.get("objectKey") or "").startswith("PROCESS:"):
            return True
        source_actions = contest.get("sourceActionTypes") or {}
        if not isinstance(source_actions, dict):
            return False
        return str(source_actions.get(str(context.player_id)) or "").upper() == "PROCESS"

    def _self_is_ahead(self, context: GameContext, contest: dict[str, Any]) -> bool:
        team_id = str(context.team_id or "").upper()
        red_point = int(contest.get("redPoint") or 0)
        blue_point = int(contest.get("bluePoint") or 0)
        if team_id == "RED":
            return red_point > blue_point
        if team_id == "BLUE":
            return blue_point > red_point
        return False

    def _should_defer_process_after_draw(self, context: GameContext) -> bool:
        opponent_id = context.opponent_player_id
        if opponent_id is None:
            return False
        return self._player_tie_key(context.player_id) > self._player_tie_key(opponent_id)

    @staticmethod
    def _player_tie_key(player_id: Any) -> tuple[int, int | str]:
        text = str(player_id)
        if text.isdigit():
            return (0, int(text))
        return (1, text)

    def _counter_latest_opponent_card(
        self, context: GameContext, contest: dict[str, Any], affordable: set[str]
    ) -> str | None:
        opponent_card = self._latest_opponent_card(context, contest)
        if opponent_card is None:
            return None
        for card in COUNTER_CARD_PREFERENCE.get(opponent_card, ()):
            if card in affordable:
                return card
        return None

    def _latest_opponent_card(self, context: GameContext, contest: dict[str, Any]) -> str | None:
        cards = contest.get("cards") or {}
        if not isinstance(cards, dict):
            return None
        opponent_team = str(context.opponent_team_id or "")
        if not opponent_team:
            return None

        latest_round = -1
        latest_card: str | None = None
        for raw_key, raw_card in cards.items():
            card = str(raw_card or "").upper()
            if card not in WINDOW_CARDS:
                continue
            key = str(raw_key)
            key_parts = key.split(":")
            team = key_parts[-1]
            if team != opponent_team:
                continue
            round_index = self._card_key_round(key_parts)
            if round_index >= latest_round:
                latest_round = round_index
                latest_card = card
        return latest_card

    @staticmethod
    def _card_key_round(key_parts: list[str]) -> int:
        if not key_parts:
            return 0
        prefix = key_parts[0]
        if len(prefix) >= 2 and prefix[0].upper() == "R" and prefix[1:].isdigit():
            return int(prefix[1:])
        return 0

    def _affordable_cards(self, player: dict[str, Any]) -> set[str]:
        resources = player.get("resources") or {}
        cards = {"ABSTAIN"}
        if self._resource_count(resources, "PASS_TOKEN") + self._resource_count(resources, "OFFICIAL_PERMIT") > 0:
            cards.add("YAN_DIE")
        if self._has_speed(player) or self._resource_count(resources, "FAST_HORSE") + self._resource_count(resources, "SHORT_HORSE") > 0:
            cards.add("QIANG_XING")
        if int(player.get("guardActionPoint") or 0) > 0:
            cards.add("BING_ZHENG")
        if float(player.get("freshness") or 0) >= 80 and int(player.get("goodFruit") or 0) > 30:
            cards.add("XIAN_GONG")
        return cards

    @staticmethod
    def _has_speed(player: dict[str, Any]) -> bool:
        for buff in player.get("buffs") or []:
            buff_type = str(buff.get("type") or buff.get("buffType") or "").upper()
            if buff_type in SPEED_BUFF_TYPES:
                return True
        return False

    @staticmethod
    def _resource_count(resources: dict[str, Any], resource_type: str) -> int:
        try:
            return int(resources.get(resource_type) or 0)
        except (TypeError, ValueError):
            return 0
