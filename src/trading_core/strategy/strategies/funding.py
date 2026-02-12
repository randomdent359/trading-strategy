"""Hyperliquid funding rate strategies — ported from legacy monitors."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from trading_core.models import MarketSnapshot, Signal
from trading_core.strategy import Strategy, register


@register
class FundingRate(Strategy):
    """Short when longs pay extreme funding, long when shorts pay.

    funding > threshold  → SHORT (longs over-leveraged)
    funding < -threshold → LONG  (shorts over-leveraged)
    """

    name = "funding_rate"
    assets = ["BTC", "ETH", "SOL"]
    exchanges = ["hyperliquid"]
    interval = "1m"
    docs = {
        "thesis": "Fade extreme funding rates on perpetual futures. When longs pay high funding, they are over-leveraged and price tends to correct downward (and vice versa).",
        "data": "Hyperliquid funding rate from the latest funding snapshot. Compares absolute rate against a configurable threshold (default 0.12%).",
        "risk": "Funding can stay elevated during strong trends. Position may be stopped out before the mean-reversion plays out.",
    }

    def __init__(self, **params: Any) -> None:
        super().__init__(**params)
        self.threshold = Decimal(str(self.params.get("threshold", 0.0012)))

    def evaluate(self, snapshot: MarketSnapshot) -> Signal | None:
        if not snapshot.funding:
            return None

        latest = snapshot.funding[-1]
        rate = latest.funding_rate

        if rate > self.threshold:
            direction = "SHORT"
            confidence = float(min(rate / (self.threshold * 3), Decimal(1)))
        elif rate < -self.threshold:
            direction = "LONG"
            confidence = float(min(-rate / (self.threshold * 3), Decimal(1)))
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


@register
class FundingOI(Strategy):
    """Extreme funding + extreme OI = maximum squeeze setup.

    Both conditions must be true:
      funding_rate > funding_threshold
      current_oi / max(historical_oi over 7d) > oi_pct / 100
    """

    name = "funding_oi"
    assets = ["BTC", "ETH", "SOL"]
    exchanges = ["hyperliquid"]
    interval = "1m"
    docs = {
        "thesis": "Extreme funding combined with high open interest signals maximum squeeze potential. Both conditions must be met, filtering for setups where crowded positioning is most likely to unwind.",
        "data": "Hyperliquid funding rate and open interest. OI is compared to the 7-day historical max from the snapshot window. Both must exceed their thresholds.",
        "risk": "Dual-filter reduces signal frequency. High OI with extreme funding can persist during parabolic moves. Squeeze timing is uncertain.",
    }

    def __init__(self, **params: Any) -> None:
        super().__init__(**params)
        self.funding_threshold = Decimal(str(self.params.get("funding_threshold", 0.0015)))
        self.oi_pct = Decimal(str(self.params.get("oi_pct", 85)))

    def evaluate(self, snapshot: MarketSnapshot) -> Signal | None:
        if not snapshot.funding:
            return None

        latest = snapshot.funding[-1]
        rate = latest.funding_rate
        current_oi = latest.open_interest

        if current_oi is None:
            return None

        # Compute OI ratio from historical funding snapshots
        oi_values = [f.open_interest for f in snapshot.funding if f.open_interest is not None]
        if not oi_values:
            return None
        max_oi = max(oi_values)
        if max_oi == 0:
            return None
        oi_ratio = current_oi / max_oi * 100  # as percentage

        abs_rate = abs(rate)
        if abs_rate > self.funding_threshold and oi_ratio > self.oi_pct:
            direction = "SHORT" if rate > 0 else "LONG"
            confidence = float(min(
                (abs_rate / (self.funding_threshold * 2)) * (oi_ratio / 100),
                Decimal(1),
            ))
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
                    "oi_ratio": str(round(oi_ratio, 1)),
                    "current_oi": str(current_oi),
                    "max_oi": str(max_oi),
                    "funding_threshold": str(self.funding_threshold),
                    "oi_pct": str(self.oi_pct),
                },
                ts=snapshot.ts,
            )

        return None
