"""Strategy abstract base class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from trading_core.models import MarketSnapshot, Signal


class Strategy(ABC):
    """Base class for all trading strategies.

    Subclasses must set the class-level attributes and implement evaluate().
    Instantiate with keyword params from config to override defaults.
    """

    name: str
    assets: list[str]
    exchanges: list[str]
    interval: str  # e.g. "1m", "5m", "1h"

    def __init__(self, **params: Any) -> None:
        self.params = params

    @abstractmethod
    def evaluate(self, snapshot: MarketSnapshot) -> Signal | None:
        """Evaluate a market snapshot and optionally emit a signal.

        Returns a Signal to open/close a position, or None to pass.
        """
        ...
