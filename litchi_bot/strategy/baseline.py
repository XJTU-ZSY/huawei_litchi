from __future__ import annotations

from .base import BaseStrategy


class BaselineStrategy(BaseStrategy):
    """Minimal strategy for protocol bring-up: always send an empty action list."""
