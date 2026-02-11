"""Polymarket exchange client — REST API."""

from __future__ import annotations

from typing import Any

import httpx


# Keywords used to filter for crypto-related prediction markets.
CRYPTO_KEYWORDS = ["BTC", "Bitcoin", "ETH", "Ethereum", "SOL", "Solana"]


class PolymarketClient:
    """Async client for the Polymarket gamma API."""

    def __init__(self, base_url: str = "https://gamma-api.polymarket.com"):
        self.base_url = base_url.rstrip("/")
        self._http: httpx.AsyncClient | None = None

    async def _get_http(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(timeout=15.0)
        return self._http

    async def close(self) -> None:
        if self._http and not self._http.is_closed:
            await self._http.aclose()

    async def get_markets(self) -> list[dict]:
        """Fetch all active prediction market series."""
        http = await self._get_http()
        resp = await http.get(f"{self.base_url}/series")
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def parse_outcome_prices(raw: Any) -> list[float]:
        """Parse outcomePrices which may be a JSON string or a list."""
        if isinstance(raw, str):
            import json
            return [float(x) for x in json.loads(raw)]
        if isinstance(raw, list):
            return [float(x) for x in raw]
        return []

    @staticmethod
    def classify_asset(title: str) -> str | None:
        """Extract the asset symbol from a market title, or None if unrelated."""
        t = title.upper()
        if "BTC" in t or "BITCOIN" in t:
            return "BTC"
        if "ETH" in t or "ETHEREUM" in t:
            return "ETH"
        if "SOL" in t or "SOLANA" in t:
            return "SOL"
        return None
