"""Tests for collector data transformation logic."""

from datetime import datetime, timezone

from trading_core.collectors.hyperliquid import _ms_to_dt
from trading_core.collectors.polymarket import _extract_markets


class TestHyperliquidHelpers:
    def test_ms_to_dt(self):
        # 2026-01-01T00:00:00Z
        dt = _ms_to_dt(1767225600000)
        assert dt.tzinfo == timezone.utc
        assert dt.year == 2026
        assert dt.month == 1
        assert dt.day == 1

    def test_ms_to_dt_fractional(self):
        dt = _ms_to_dt(1767225600500)
        assert dt.microsecond == 500000


class TestPolymarketExtraction:
    def test_extract_btc_market(self):
        markets = [
            {
                "conditionId": "0xabc",
                "question": "Will BTC be above 100k by March?",
                "outcomePrices": [0.72, 0.28],
                "volume24hr": 50000,
                "liquidity": 120000,
            }
        ]
        rows = _extract_markets(markets, ["BTC", "ETH", "SOL"])
        assert len(rows) == 1
        assert rows[0]["asset"] == "BTC"
        assert rows[0]["market_id"] == "0xabc"
        assert rows[0]["yes_price"] == 0.72
        assert rows[0]["no_price"] == 0.28

    def test_filters_non_crypto_markets(self):
        markets = [
            {
                "conditionId": "0x123",
                "question": "Will the US economy grow in Q2?",
                "outcomePrices": [0.6, 0.4],
            }
        ]
        rows = _extract_markets(markets, ["BTC", "ETH", "SOL"])
        assert len(rows) == 0

    def test_handles_stringified_prices(self):
        markets = [
            {
                "conditionId": "0xdef",
                "question": "ETH above 5000?",
                "outcomePrices": '[0.45, 0.55]',
            }
        ]
        rows = _extract_markets(markets, ["BTC", "ETH", "SOL"])
        assert len(rows) == 1
        assert rows[0]["yes_price"] == 0.45

    def test_skips_markets_without_id(self):
        markets = [
            {
                "question": "SOL above $200?",
                "outcomePrices": [0.3, 0.7],
            }
        ]
        rows = _extract_markets(markets, ["BTC", "ETH", "SOL"])
        assert len(rows) == 0

    def test_multiple_markets(self):
        markets = [
            {
                "conditionId": "0x1",
                "question": "BTC 100k?",
                "outcomePrices": [0.8, 0.2],
            },
            {
                "conditionId": "0x2",
                "question": "Weather in Paris?",
                "outcomePrices": [0.5, 0.5],
            },
            {
                "conditionId": "0x3",
                "question": "Solana TPS record?",
                "outcomePrices": [0.6, 0.4],
            },
        ]
        rows = _extract_markets(markets, ["BTC", "ETH", "SOL"])
        assert len(rows) == 2
        assets = {r["asset"] for r in rows}
        assert assets == {"BTC", "SOL"}

    def test_respects_asset_filter(self):
        markets = [
            {
                "conditionId": "0x1",
                "question": "BTC 100k?",
                "outcomePrices": [0.8, 0.2],
            },
            {
                "conditionId": "0x2",
                "question": "ETH 5k?",
                "outcomePrices": [0.5, 0.5],
            },
        ]
        rows = _extract_markets(markets, ["BTC"])
        assert len(rows) == 1
        assert rows[0]["asset"] == "BTC"
