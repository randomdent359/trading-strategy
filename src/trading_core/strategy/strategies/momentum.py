"""Momentum breakout strategy — Bollinger Band breakout with volume confirmation."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from trading_core.models import MarketSnapshot, Signal
from trading_core.strategy import Strategy, register
from trading_core.strategy.indicators import bollinger_bands


@register
class MomentumBreakout(Strategy):
    """Enter on Bollinger Band breakouts confirmed by volume spike.

    Price closes above upper band + volume > volume_mult * SMA(volume) → LONG
    Price closes below lower band + volume > volume_mult * SMA(volume) → SHORT
    """

    name = "momentum_breakout"
    assets = ["BTC", "ETH", "SOL"]
    exchanges = ["hyperliquid"]
    interval = "5m"
    docs = {
        "thesis": "Enter on Bollinger Band breakouts confirmed by a volume spike. Price closing outside the bands with elevated volume signals genuine momentum rather than noise.",
        "data": "Hyperliquid 5m candles — close prices for Bollinger Bands (default 20-period, 2 std) and volume for the multiplier filter (default 1.5x average).",
        "risk": "False breakouts are common; volume confirmation reduces but does not eliminate them. Ranging markets generate whipsaws. Wider bands reduce signals but increase reliability.",
    }

    def __init__(self, **params: Any) -> None:
        super().__init__(**params)
        self.bb_period = int(self.params.get("bb_period", 20))
        self.bb_std = float(self.params.get("bb_std", 2))
        self.volume_mult = Decimal(str(self.params.get("volume_mult", 1.5)))

    def evaluate(self, snapshot: MarketSnapshot) -> Signal | None:
        if not snapshot.candles or len(snapshot.candles) < self.bb_period:
            return None

        closes = [c.close for c in snapshot.candles]
        bands = bollinger_bands(closes, period=self.bb_period, num_std=self.bb_std)
        if bands is None:
            return None

        lower, middle, upper = bands
        latest = snapshot.candles[-1]
        price = latest.close

        # Volume confirmation: current volume > volume_mult * average volume
        volumes = [c.volume for c in snapshot.candles[-self.bb_period:]]
        avg_volume = sum(volumes) / len(volumes)
        if avg_volume == 0:
            return None
        volume_ok = latest.volume > self.volume_mult * avg_volume

        if not volume_ok:
            return None

        if price > upper:
            direction = "LONG"
            band_width = upper - middle
            confidence = float(min(
                (price - upper) / band_width if band_width > 0 else Decimal(0),
                Decimal(1),
            ))
        elif price < lower:
            direction = "SHORT"
            band_width = middle - lower
            confidence = float(min(
                (lower - price) / band_width if band_width > 0 else Decimal(0),
                Decimal(1),
            ))
        else:
            return None

        return Signal(
            strategy=self.name,
            asset=snapshot.asset,
            exchange="hyperliquid",
            direction=direction,
            confidence=confidence,
            entry_price=price,
            metadata={
                "bb_lower": str(round(lower, 2)),
                "bb_middle": str(round(middle, 2)),
                "bb_upper": str(round(upper, 2)),
                "volume": str(latest.volume),
                "avg_volume": str(round(avg_volume, 2)),
                "volume_ratio": str(round(latest.volume / avg_volume, 2)),
            },
            ts=snapshot.ts,
        )
