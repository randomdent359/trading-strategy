"""Hyperliquid exchange client — REST + WebSocket."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncGenerator
from typing import Any

import httpx
import websockets


class HyperliquidClient:
    """Async client for Hyperliquid's REST and WebSocket APIs."""

    def __init__(
        self,
        base_url: str = "https://api.hyperliquid.xyz",
        ws_url: str = "wss://api.hyperliquid.xyz/ws",
    ):
        self.base_url = base_url.rstrip("/")
        self.ws_url = ws_url
        self._http: httpx.AsyncClient | None = None

    async def _get_http(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(timeout=15.0)
        return self._http

    async def close(self) -> None:
        if self._http and not self._http.is_closed:
            await self._http.aclose()

    # --- REST ---

    async def _post_info(self, payload: dict) -> Any:
        http = await self._get_http()
        resp = await http.post(f"{self.base_url}/info", json=payload)
        resp.raise_for_status()
        return resp.json()

    async def get_meta_and_asset_ctxs(self) -> tuple[dict, list[dict]]:
        """Fetch universe metadata and per-asset contexts.

        Returns (meta, [asset_ctx, ...]) where each asset_ctx contains
        funding, openInterest, markPx, etc.
        """
        data = await self._post_info({"type": "metaAndAssetCtxs"})
        meta = data[0]
        asset_ctxs = data[1]
        return meta, asset_ctxs

    async def get_candle_snapshot(
        self,
        coin: str,
        interval: str,
        start_time_ms: int,
        end_time_ms: int,
    ) -> list[dict]:
        """Fetch historical candles for backfill.

        Returns list of candle dicts with keys: t, T, s, i, o, c, h, l, v, n.
        """
        data = await self._post_info({
            "type": "candleSnapshot",
            "req": {
                "coin": coin,
                "interval": interval,
                "startTime": start_time_ms,
                "endTime": end_time_ms,
            },
        })
        return data

    # --- WebSocket ---

    async def subscribe_candles(
        self,
        coins: list[str],
        interval: str = "1m",
    ) -> AsyncGenerator[dict, None]:
        """Subscribe to real-time candle updates via WebSocket.

        Yields candle dicts as they arrive. Caller is responsible for
        reconnection logic (this generator exits on disconnect).
        """
        async with websockets.connect(self.ws_url) as ws:
            for coin in coins:
                await ws.send(json.dumps({
                    "method": "subscribe",
                    "subscription": {"type": "candle", "coin": coin, "interval": interval},
                }))

            async for raw in ws:
                msg = json.loads(raw)
                if msg.get("channel") == "candle":
                    yield msg["data"]
