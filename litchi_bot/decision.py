from __future__ import annotations

from typing import Any

from .game_state import GameContext, GameMemory, GameSnapshot
from .strategy.baseline import BaselineStrategy


class DecisionEngine:
    def __init__(self, memory: GameMemory) -> None:
        self.strategy = BaselineStrategy(memory)
        self.last_reason = "init"

    def decide(self, context: GameContext, snapshot: GameSnapshot) -> list[dict[str, Any]]:
        try:
            actions = self.strategy.decide(context, snapshot)
            self.last_reason = self.strategy.last_reason
            return self._dedupe_categories(actions)
        except Exception as exc:
            self.last_reason = f"decision exception: {exc}"
            return []

    def _dedupe_categories(self, actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        selected: list[dict[str, Any]] = []
        seen: set[str] = set()
        for action in actions:
            category = self._category(action.get("action"))
            if category in seen:
                continue
            seen.add(category)
            selected.append(action)
        return selected

    @staticmethod
    def _category(action_name: Any) -> str:
        if action_name == "WINDOW_CARD":
            return "window"
        if action_name in {"SQUAD_SCOUT", "SQUAD_CLEAR", "SQUAD_REINFORCE", "SQUAD_WEAKEN"}:
            return "squad"
        return "main"
