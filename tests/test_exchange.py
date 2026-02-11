"""Tests for exchange client helpers."""

from trading_core.exchange.hyperliquid import HyperliquidClient
from trading_core.exchange.polymarket import PolymarketClient


class TestHyperliquidClient:
    def test_default_urls(self):
        c = HyperliquidClient()
        assert c.base_url == "https://api.hyperliquid.xyz"
        assert c.ws_url == "wss://api.hyperliquid.xyz/ws"

    def test_custom_urls(self):
        c = HyperliquidClient(base_url="https://custom.api/", ws_url="wss://custom.ws/")
        assert c.base_url == "https://custom.api"
        assert c.ws_url == "wss://custom.ws/"


class TestPolymarketClient:
    def test_default_url(self):
        c = PolymarketClient()
        assert c.base_url == "https://gamma-api.polymarket.com"

    def test_parse_outcome_prices_list(self):
        assert PolymarketClient.parse_outcome_prices([0.72, 0.28]) == [0.72, 0.28]

    def test_parse_outcome_prices_json_string(self):
        assert PolymarketClient.parse_outcome_prices('[0.72, 0.28]') == [0.72, 0.28]

    def test_parse_outcome_prices_empty(self):
        assert PolymarketClient.parse_outcome_prices(None) == []
        assert PolymarketClient.parse_outcome_prices("") == []

    def test_classify_asset_btc(self):
        assert PolymarketClient.classify_asset("Will BTC hit 100k?") == "BTC"
        assert PolymarketClient.classify_asset("Bitcoin above 100k by March") == "BTC"

    def test_classify_asset_eth(self):
        assert PolymarketClient.classify_asset("ETH price UP this week?") == "ETH"
        assert PolymarketClient.classify_asset("Ethereum merge complete?") == "ETH"

    def test_classify_asset_sol(self):
        assert PolymarketClient.classify_asset("SOL above $200?") == "SOL"
        assert PolymarketClient.classify_asset("Solana TPS record?") == "SOL"

    def test_classify_asset_unrelated(self):
        assert PolymarketClient.classify_asset("US election 2026") is None
        assert PolymarketClient.classify_asset("Will it rain tomorrow?") is None

    def test_classify_asset_rejects_substring_matches(self):
        assert PolymarketClient.classify_asset("Senator guilty of soliciting a child?") is None
        assert PolymarketClient.classify_asset("Next Prime Minister of the Netherlands?") is None
        assert PolymarketClient.classify_asset("Will the method work?") is None
        assert PolymarketClient.classify_asset("Solving world hunger") is None
