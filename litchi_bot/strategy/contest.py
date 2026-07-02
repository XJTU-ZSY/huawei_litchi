from __future__ import annotations

from typing import Any

from ..game_state import GameContext, GameSnapshot, same_player_id


HORSE_RESOURCE_TYPES = {"FAST_HORSE", "SHORT_HORSE"}
HORSE_TRANSFER_TEMPLATE_IDS = {"T06"}
HORSE_TRANSFER_PROCESS_TYPES = {"HORSE_TRANSFER"}
HORSE_SPEED_BUFF_TYPES = {"FAST_HORSE", "SHORT_HORSE", "RUSH_SPEED"}


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
        player = snapshot.self_player
        resources = player.get("resources") or {}
        contest_type = contest.get("contestType")
        if contest_type == "TASK":
            return self._choose_task_contest_card(context, snapshot, contest)
        if player.get("guardActionPoint", 0) > 0 and contest_type in {"GATE", "PASS", "OBSTACLE"}:
            return "BING_ZHENG"
        if resources.get("PASS_TOKEN", 0) + resources.get("OFFICIAL_PERMIT", 0) > 0:
            return "YAN_DIE"
        has_speed = self._has_horse_speed_buff(player)
        if has_speed or self._horse_resource_count(resources) > 0:
            if not has_speed and self._should_preserve_horse_for_task(context, snapshot, contest):
                return self._fallback_non_horse_card(player)
            return "QIANG_XING"
        return self._fallback_non_horse_card(player)

    def _choose_task_contest_card(
        self,
        context: GameContext,
        snapshot: GameSnapshot,
        contest: dict[str, Any],
    ) -> str:
        player = snapshot.self_player
        resources = player.get("resources") or {}
        has_speed = self._has_horse_speed_buff(player)
        if has_speed:
            return "QIANG_XING"
        if self._horse_resource_count(resources) > 0 and not self._should_preserve_horse_for_task(
            context,
            snapshot,
            contest,
        ):
            return "QIANG_XING"
        if self._can_pay_xian_gong(player):
            return "XIAN_GONG"
        if player.get("guardActionPoint", 0) > 0:
            return "BING_ZHENG"
        if resources.get("PASS_TOKEN", 0) + resources.get("OFFICIAL_PERMIT", 0) > 0:
            return "YAN_DIE"
        return "ABSTAIN"

    def _fallback_non_horse_card(self, player: dict[str, Any]) -> str:
        if self._can_pay_xian_gong(player):
            return "XIAN_GONG"
        return "ABSTAIN"

    @staticmethod
    def _can_pay_xian_gong(player: dict[str, Any]) -> bool:
        return float(player.get("freshness") or 0) >= 80 and int(player.get("goodFruit") or 0) > 30

    def _should_preserve_horse_for_task(
        self,
        context: GameContext,
        snapshot: GameSnapshot,
        contest: dict[str, Any],
    ) -> bool:
        if contest.get("contestType") != "TASK":
            return False
        resources = snapshot.self_player.get("resources") or {}
        if self._horse_resource_count(resources) != 1:
            return False
        task_id = self._contest_task_id(context, contest)
        task = self._find_task(snapshot, task_id)
        if task is None and task_id:
            task = {"taskId": task_id, "taskTemplateId": self._template_id_from_task_id(task_id)}
        return task is not None and self._task_accepts_horse_resource(context, task)

    @staticmethod
    def _has_horse_speed_buff(player: dict[str, Any]) -> bool:
        return any((buff.get("type") in HORSE_SPEED_BUFF_TYPES) for buff in player.get("buffs") or [])

    @staticmethod
    def _horse_resource_count(resources: dict[str, Any]) -> int:
        return sum(int(resources.get(resource_type) or 0) for resource_type in HORSE_RESOURCE_TYPES)

    @staticmethod
    def _contest_task_id(context: GameContext, contest: dict[str, Any]) -> str:
        task_id = contest.get("taskId")
        if task_id:
            return str(task_id)
        source_task_ids = contest.get("sourceTaskIds") or {}
        for key in (context.player_id, str(context.player_id)):
            task_id = source_task_ids.get(key)
            if task_id:
                return str(task_id)
        return ""

    @staticmethod
    def _find_task(snapshot: GameSnapshot, task_id: str) -> dict[str, Any] | None:
        if not task_id:
            return None
        for task in snapshot.tasks:
            if str(task.get("taskId") or "") == task_id:
                return task
        return None

    @staticmethod
    def _template_id_from_task_id(task_id: str) -> str:
        return task_id.split("_", 1)[0] if task_id else ""

    def _task_accepts_horse_resource(self, context: GameContext, task: dict[str, Any]) -> bool:
        template_id = str(task.get("taskTemplateId") or self._template_id_from_task_id(str(task.get("taskId") or "")))
        process_type = str(task.get("processType") or "")
        if template_id in HORSE_TRANSFER_TEMPLATE_IDS or process_type in HORSE_TRANSFER_PROCESS_TYPES:
            return True
        template = self._task_template(context, template_id)
        if template is None:
            return False
        return (
            str(template.get("taskTemplateId") or "") in HORSE_TRANSFER_TEMPLATE_IDS
            or str(template.get("processType") or "") in HORSE_TRANSFER_PROCESS_TYPES
        )

    @staticmethod
    def _task_template(context: GameContext, template_id: str) -> dict[str, Any] | None:
        if not template_id:
            return None
        raw_start = context.raw_start or {}
        template_groups = [raw_start.get("taskTemplates") or []]
        map_data = raw_start.get("map") or {}
        template_groups.append(map_data.get("taskTemplates") or [])
        for templates in template_groups:
            for template in templates:
                if str(template.get("taskTemplateId") or "") == template_id:
                    return template
        return None
