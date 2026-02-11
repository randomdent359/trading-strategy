"""Tests for technical indicators — known-value validation."""

from __future__ import annotations

from decimal import Decimal

import pytest

from trading_core.strategy.indicators import bollinger_bands, rsi


class TestRSI:
    def test_insufficient_data_returns_none(self):
        assert rsi([Decimal(i) for i in range(14)], period=14) is None
        assert rsi([], period=14) is None

    def test_exactly_enough_data(self):
        # 15 closes → 14 deltas → exactly one period
        closes = [Decimal(i) for i in range(15)]
        result = rsi(closes, period=14)
        assert result is not None

    def test_all_gains_returns_100(self):
        # Monotonically increasing → RSI = 100
        closes = [Decimal(i) for i in range(20)]
        result = rsi(closes, period=14)
        assert result == Decimal(100)

    def test_all_losses_returns_0(self):
        # Monotonically decreasing → RSI = 0
        closes = [Decimal(20 - i) for i in range(20)]
        result = rsi(closes, period=14)
        assert result == Decimal(0)

    def test_equal_gains_and_losses_around_50(self):
        # Alternating up/down → RSI near 50
        closes = []
        price = Decimal(100)
        for i in range(30):
            closes.append(price)
            price += Decimal(1) if i % 2 == 0 else Decimal(-1)
        result = rsi(closes, period=14)
        assert result is not None
        assert Decimal(40) < result < Decimal(60)

    def test_known_value(self):
        # Hand-calculated example: 14 gains of +1, then 5 losses of -1
        closes = [Decimal(100)]
        for _ in range(14):
            closes.append(closes[-1] + Decimal(1))
        for _ in range(5):
            closes.append(closes[-1] - Decimal(1))
        result = rsi(closes, period=14)
        assert result is not None
        # After 14 gains: avg_gain=1, avg_loss=0 → RSI seed=100
        # Then Wilder smoothing through 5 losses brings it down
        assert Decimal(40) < result < Decimal(80)

    def test_custom_period(self):
        closes = [Decimal(i) for i in range(10)]
        result = rsi(closes, period=5)
        assert result is not None
        assert result == Decimal(100)  # all gains


class TestBollingerBands:
    def test_insufficient_data_returns_none(self):
        assert bollinger_bands([Decimal(1)] * 19, period=20) is None
        assert bollinger_bands([], period=20) is None

    def test_constant_prices_bands_equal_middle(self):
        closes = [Decimal(100)] * 20
        result = bollinger_bands(closes, period=20)
        assert result is not None
        lower, middle, upper = result
        assert middle == Decimal(100)
        assert lower == Decimal(100)
        assert upper == Decimal(100)

    def test_symmetric_bands(self):
        closes = [Decimal(100)] * 10 + [Decimal(110)] * 10
        result = bollinger_bands(closes, period=20, num_std=2)
        assert result is not None
        lower, middle, upper = result
        # Bands should be symmetric around middle
        assert upper - middle == pytest.approx(middle - lower, abs=Decimal("0.0001"))

    def test_middle_is_sma(self):
        closes = [Decimal(i) for i in range(1, 21)]
        result = bollinger_bands(closes, period=20)
        assert result is not None
        _, middle, _ = result
        expected_sma = sum(Decimal(i) for i in range(1, 21)) / 20
        assert middle == expected_sma

    def test_wider_std_gives_wider_bands(self):
        closes = [Decimal(100 + i % 5) for i in range(25)]
        narrow = bollinger_bands(closes, period=20, num_std=1)
        wide = bollinger_bands(closes, period=20, num_std=3)
        assert narrow is not None and wide is not None
        narrow_width = narrow[2] - narrow[0]
        wide_width = wide[2] - wide[0]
        assert wide_width > narrow_width

    def test_uses_last_n_closes(self):
        # First 20 values don't matter; only last 20 are used
        closes = [Decimal(50)] * 20 + [Decimal(100)] * 20
        result = bollinger_bands(closes, period=20)
        assert result is not None
        _, middle, _ = result
        assert middle == Decimal(100)
