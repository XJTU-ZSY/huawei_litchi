from __future__ import annotations

from typing import Any


class BaseStrategy:
    def on_start(self, start_data: dict[str, Any]) -> None:
        pass

    def decide(self, inquire_data: dict[str, Any]) -> list[dict[str, Any]]:
        return []
