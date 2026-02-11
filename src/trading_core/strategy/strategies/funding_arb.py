"""Funding arbitrage strategy — collect funding at a lower threshold."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from trading_core.models import MarketSnapshot, Signal
from trading_core.strategy import Strategy, register


@register
class FundingArb(Strategy):
    """Collect funding payments by positioning against the dominant side.

    Uses a lower threshold than FundingRate to capture more frequent,
    smaller funding arbitrage opportunities.

    funding > threshold  → SHORT (collect funding from longs)
    funding < -threshold → LONG  (collect funding from shorts)
    """

    name = "funding_arb"
    assets = ["BTC", "ETH", "SOL"]
    exchanges = ["hyperliquid"]
    interval = "1m"

    def __init__(self, **params: Any) -> None:
        super().__init__(**params)
        self.threshold = Decimal(str(self.params.get("threshold", 0.0005)))

    def evaluate(self, snapshot: MarketSnapshot) -> Signal | None:
        if not snapshot.funding:
            return None

        latest = snapshot.funding[-1]
        rate = latest.funding_rate

        if rate > self.threshold:
            direction = "SHORT"
            confidence = float(min(rate / (self.threshold * 4), Decimal(1)))
        elif rate < -self.threshold:
            direction = "LONG"
            confidence = float(min(-rate / (self.threshold * 4), Decimal(1)))
        else:
            return None

        entry_price = latest.mark_price if latest.mark_price else Decimal(0)

        return Signal(
            strategy=self.name,
            asset=snapshot.asset,
            exchange="hyperliquid",
            direction=direction,
            confidence=confidence,
            entry_price=entry_price,
            metadata={
                "funding_rate": str(rate),
                "threshold": str(self.threshold),
            },
            ts=snapshot.ts,
        )
