"""Polymarket exchange client — REST API.

Supports both the gamma API (gamma-api.polymarket.com) and the CLOB API
(clob.polymarket.com). The gamma API is preferred — it returns richer
market objects with outcomePrices already included.

The CLOB API wraps results in {"data": [...], "next_cursor": "..."}
and uses snake_case field names (condition_id vs conditionId).
"""

from __future__ import annotations

from typing import Any

import httpx


class PolymarketClient:
    """Async client for the Polymarket API."""

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

    async def get_markets(self, limit: int = 100) -> list[dict]:
        """Fetch active prediction markets (paginated).

        Handles both response formats:
        - Gamma API: returns a bare list of market dicts
        - CLOB API: returns {"data": [...], "next_cursor": "..."}
        """
        http = await self._get_http()
        all_markets: list[dict] = []
        offset = 0
        next_cursor: str | None = None

        while True:
            params: dict[str, Any] = {"limit": limit}

            if next_cursor is not None:
                # CLOB-style cursor pagination
                params["next_cursor"] = next_cursor
            else:
                params["closed"] = "false"
                if offset > 0:
                    params["offset"] = offset

            resp = await http.get(f"{self.base_url}/markets", params=params)
            resp.raise_for_status()
            body = resp.json()

            # Detect response format
            if isinstance(body, dict) and "data" in body:
                # CLOB API format: {"data": [...], "next_cursor": "..."}
                page = body["data"]
                next_cursor = body.get("next_cursor") or None
                if not page:
                    break
                all_markets.extend(page)
                if next_cursor is None or next_cursor == "LTE=":
                    break
            elif isinstance(body, list):
                # Gamma API format: bare list
                if not body:
                    break
                all_markets.extend(body)
                if len(body) < limit:
                    break
                offset += limit
                next_cursor = None
            else:
                break

        return all_markets

    @staticmethod
    def normalize_market(market: dict) -> dict:
        """Normalize a market dict to use consistent camelCase field names.

        The CLOB API uses snake_case (condition_id, question_id) while
        the gamma API uses camelCase (conditionId, questionID). This
        normalizes to the gamma API convention.
        """
        return {
            "conditionId": market.get("conditionId") or market.get("condition_id", ""),
            "question": market.get("question", ""),
            "title": market.get("title", ""),
            "outcomePrices": market.get("outcomePrices", []),
            "volume24hr": market.get("volume24hr") or market.get("volume", 0),
            "liquidity": market.get("liquidity") or market.get("liquidityNum", 0),
            "id": market.get("id", ""),
        }

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
        """Extract the asset symbol from a market title, or None if unrelated."""
        t = title.upper()
        if "BTC" in t or "BITCOIN" in t:
            return "BTC"
        if "ETH" in t or "ETHEREUM" in t:
            return "ETH"
        if "SOL" in t or "SOLANA" in t:
            return "SOL"
        return None
