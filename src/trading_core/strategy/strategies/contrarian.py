"""Polymarket contrarian strategies — ported from legacy monitors."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from trading_core.models import MarketSnapshot, Signal
from trading_core.strategy import Strategy, register


@register
class ContrarianPure(Strategy):
    """Bet against consensus when prediction market probability exceeds threshold.

    yes_price > threshold → SHORT (consensus too high, contrarian bets on "no")
    yes_price < (1 - threshold) → LONG (consensus too low, contrarian bets on "yes")
    """

    name = "contrarian_pure"
    assets = ["BTC", "ETH", "SOL"]
    exchanges = ["polymarket"]
    interval = "10m"

    def __init__(self, **params: Any) -> None:
        super().__init__(**params)
        self.threshold = Decimal(str(self.params.get("threshold", 0.72)))

    def evaluate(self, snapshot: MarketSnapshot) -> Signal | None:
        if not snapshot.polymarket:
            return None

        # Use the most recent Polymarket observation
        market = snapshot.polymarket[-1]
        if market.yes_price is None:
            return None

        yes = market.yes_price
        if yes > self.threshold:
            direction = "SHORT"
            confidence = float(min((yes - self.threshold) / (Decimal(1) - self.threshold), Decimal(1)))
        elif yes < (Decimal(1) - self.threshold):
            direction = "LONG"
            confidence = float(min(((Decimal(1) - self.threshold) - yes) / (Decimal(1) - self.threshold), Decimal(1)))
        else:
            return None

        return Signal(
            strategy=self.name,
            asset=snapshot.asset,
            exchange="polymarket",
            direction=direction,
            confidence=confidence,
            entry_price=yes,
            metadata={
                "market_id": market.market_id,
                "market_title": market.market_title,
                "yes_price": str(yes),
                "threshold": str(self.threshold),
            },
            ts=snapshot.ts,
        )


@register
class ContrarianStrength(Strategy):
    """Higher-bar contrarian — only fires on very strong consensus (>80%)."""

    name = "contrarian_strength"
    assets = ["BTC", "ETH", "SOL"]
    exchanges = ["polymarket"]
    interval = "10m"

    def __init__(self, **params: Any) -> None:
        super().__init__(**params)
        self.threshold = Decimal(str(self.params.get("threshold", 0.80)))

    def evaluate(self, snapshot: MarketSnapshot) -> Signal | None:
        if not snapshot.polymarket:
            return None

        market = snapshot.polymarket[-1]
        if market.yes_price is None:
            return None

        yes = market.yes_price
        if yes > self.threshold:
            direction = "SHORT"
            confidence = float(min((yes - self.threshold) / (Decimal(1) - self.threshold), Decimal(1)))
        elif yes < (Decimal(1) - self.threshold):
            direction = "LONG"
            confidence = float(min(((Decimal(1) - self.threshold) - yes) / (Decimal(1) - self.threshold), Decimal(1)))
        else:
            return None

        return Signal(
            strategy=self.name,
            asset=snapshot.asset,
            exchange="polymarket",
            direction=direction,
            confidence=confidence,
            entry_price=yes,
            metadata={
                "market_id": market.market_id,
                "market_title": market.market_title,
                "yes_price": str(yes),
                "threshold": str(self.threshold),
            },
            ts=snapshot.ts,
        )
