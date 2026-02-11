"""Strategy abstract base class."""

from __future__ import annotations

from abc import ABC, abstractmethod

from trading_core.models import MarketSnapshot, Signal


class Strategy(ABC):
    """Base class for all trading strategies.

    Subclasses must set the class-level attributes and implement evaluate().
    """

    name: str
    assets: list[str]
    exchanges: list[str]
    interval: str  # e.g. "1m", "5m", "1h"

    @abstractmethod
    def evaluate(self, snapshot: MarketSnapshot) -> Signal | None:
        """Evaluate a market snapshot and optionally emit a signal.

        Returns a Signal to open/close a position, or None to pass.
        """
        ...
