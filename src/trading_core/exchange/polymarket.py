"""Polymarket exchange client — gamma API (/events with tag filtering)."""

from __future__ import annotations

import re
from typing import Any

import httpx

# Tag IDs for crypto-related event filtering on the gamma API.
TAG_IDS = {
    "crypto_prices": 1312,
    "bitcoin": 235,
    "ethereum": 39,
    "solana": 818,
    "up_or_down": 102127,
}

# Default tags to query — covers price targets and short-term up/down markets.
DEFAULT_TAG_IDS = [1312, 235, 39, 818, 102127]


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

    async def get_events(
        self,
        tag_id: int,
        limit: int = 100,
        closed: bool = False,
    ) -> list[dict]:
        """Fetch events for a given tag, paginated.

        Each event contains a nested ``markets`` list with individual
        prediction markets including outcomePrices.
        """
        http = await self._get_http()
        all_events: list[dict] = []
        offset = 0

        while True:
            params: dict[str, Any] = {
                "tag_id": tag_id,
                "closed": str(closed).lower(),
                "limit": limit,
            }
            if offset > 0:
                params["offset"] = offset

            resp = await http.get(f"{self.base_url}/events", params=params)
            resp.raise_for_status()
            page = resp.json()

            if not isinstance(page, list) or not page:
                break

            all_events.extend(page)
            if len(page) < limit:
                break
            offset += limit

        return all_events

    async def get_crypto_markets(
        self,
        tag_ids: list[int] | None = None,
    ) -> list[dict]:
        """Fetch markets from multiple crypto-related tags.

        Queries /events for each tag, extracts nested markets, and
        deduplicates by conditionId.
        """
        if tag_ids is None:
            tag_ids = DEFAULT_TAG_IDS

        seen: set[str] = set()
        all_markets: list[dict] = []

        for tag_id in tag_ids:
            events = await self.get_events(tag_id)
            for event in events:
                for market in event.get("markets", []):
                    if not isinstance(market, dict):
                        continue
                    cid = market.get("conditionId", "")
                    if cid and cid not in seen:
                        seen.add(cid)
                        all_markets.append(market)

        return all_markets

    @staticmethod
    def parse_outcome_prices(raw: Any) -> list[float]:
        """Parse outcomePrices which may be a JSON string or a list."""
        if isinstance(raw, str) and raw.strip():
            import json
            return [float(x) for x in json.loads(raw)]
        if isinstance(raw, list):
            return [float(x) for x in raw]
        return []

    @staticmethod
    def classify_asset(title: str) -> str | None:
        """Extract the asset symbol from a market title, or None if unrelated.

        Uses word-boundary matching to avoid false positives like
        "SOL" in "soliciting" or "ETH" in "Netherlands".
        """
        if re.search(r'\bBTC\b|\bBitcoin\b', title, re.IGNORECASE):
            return "BTC"
        if re.search(r'\bETH\b|\bEthereum\b', title, re.IGNORECASE):
            return "ETH"
        if re.search(r'\bSOL\b|\bSolana\b', title, re.IGNORECASE):
            return "SOL"
        return None
