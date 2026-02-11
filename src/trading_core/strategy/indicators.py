"""Technical indicators — pure functions on price series."""

from __future__ import annotations

from decimal import Decimal
from statistics import mean


def rsi(closes: list[Decimal], period: int = 14) -> Decimal | None:
    """Relative Strength Index (Wilder's smoothing).

    Returns a Decimal in [0, 100] or None if there are fewer than
    ``period + 1`` data points.
    """
    if len(closes) < period + 1:
        return None

    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]

    # Seed with simple average of first *period* changes
    gains = [d if d > 0 else Decimal(0) for d in deltas[:period]]
    losses = [-d if d < 0 else Decimal(0) for d in deltas[:period]]
    avg_gain = Decimal(mean(gains))
    avg_loss = Decimal(mean(losses))

    # Wilder smoothing over remaining deltas
    for d in deltas[period:]:
        avg_gain = (avg_gain * (period - 1) + (d if d > 0 else Decimal(0))) / period
        avg_loss = (avg_loss * (period - 1) + (-d if d < 0 else Decimal(0))) / period

    if avg_loss == 0:
        return Decimal(100)
    rs = avg_gain / avg_loss
    return Decimal(100) - Decimal(100) / (1 + rs)


def bollinger_bands(
    closes: list[Decimal],
    period: int = 20,
    num_std: int | float = 2,
) -> tuple[Decimal, Decimal, Decimal] | None:
    """Bollinger Bands (SMA +/- num_std * stdev).

    Returns ``(lower, middle, upper)`` or None if fewer than *period* data
    points are available.
    """
    if len(closes) < period:
        return None

    window = closes[-period:]
    middle = Decimal(mean(window))
    variance = sum((p - middle) ** 2 for p in window) / period
    std = variance.sqrt() if hasattr(variance, "sqrt") else Decimal(variance ** Decimal("0.5"))
    offset = std * Decimal(str(num_std))
    return (middle - offset, middle, middle + offset)
