"""RSI mean-reversion strategy."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from trading_core.models import MarketSnapshot, Signal
from trading_core.strategy import Strategy, register
from trading_core.strategy.indicators import rsi


@register
class RSIMeanReversion(Strategy):
    """Fade overbought/oversold RSI readings on Hyperliquid perps.

    RSI > overbought → SHORT (expect reversion down)
    RSI < oversold   → LONG  (expect reversion up)
    """

    name = "rsi_mean_reversion"
    assets = ["BTC", "ETH", "SOL"]
    exchanges = ["hyperliquid"]
    interval = "5m"
    docs = {
        "thesis": "Fade overbought/oversold RSI readings on Hyperliquid perps. Extreme RSI values tend to revert to the mean as momentum exhausts.",
        "data": "Hyperliquid 5m candle close prices fed into a 14-period RSI. Overbought default 75, oversold default 25.",
        "risk": "RSI can stay overbought/oversold in strong trends, leading to early entries against the trend. Works best in ranging or choppy markets.",
    }

    def __init__(self, **params: Any) -> None:
        super().__init__(**params)
        self.period = int(self.params.get("period", 14))
        self.overbought = Decimal(str(self.params.get("overbought", 75)))
        self.oversold = Decimal(str(self.params.get("oversold", 25)))

    def evaluate(self, snapshot: MarketSnapshot) -> Signal | None:
        if not snapshot.candles:
            return None

        closes = [c.close for c in snapshot.candles]
        rsi_value = rsi(closes, period=self.period)
        if rsi_value is None:
            return None

        if rsi_value > self.overbought:
            direction = "SHORT"
            confidence = float(min(
                (rsi_value - self.overbought) / (Decimal(100) - self.overbought),
                Decimal(1),
            ))
        elif rsi_value < self.oversold:
            direction = "LONG"
            confidence = float(min(
                (self.oversold - rsi_value) / self.oversold,
                Decimal(1),
            ))
        else:
            return None

        entry_price = closes[-1]

        return Signal(
            strategy=self.name,
            asset=snapshot.asset,
            exchange="hyperliquid",
            direction=direction,
            confidence=confidence,
            entry_price=entry_price,
            metadata={
                "rsi": str(round(rsi_value, 2)),
                "period": self.period,
                "overbought": str(self.overbought),
                "oversold": str(self.oversold),
            },
            ts=snapshot.ts,
        )
