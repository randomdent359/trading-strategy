"""PriceOracle — in-memory price cache fed by Hyperliquid WebSocket and DB queries."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from decimal import Decimal

import structlog
from sqlalchemy import desc
from sqlalchemy.orm import Session

from trading_core.db.tables.market_data import PolymarketMarketRow

log = structlog.get_logger("price_oracle")


@dataclass
class PriceEntry:
    """A cached price with metadata."""

    price: Decimal
    updated_at: float  # time.monotonic()
    source: str  # "ws", "db", "manual"


class PriceOracle:
    """In-process price cache: HL WebSocket for real-time mids, DB for Polymarket."""

    def __init__(
        self,
        assets: list[str],
        hl_ws_url: str = "wss://api.hyperliquid.xyz/ws",
        staleness_threshold_s: float = 30.0,
        pm_staleness_threshold_s: float = 600.0,
    ) -> None:
        self._assets = set(assets)
        self._hl_ws_url = hl_ws_url
        self._staleness_s = staleness_threshold_s
        self._pm_staleness_s = pm_staleness_threshold_s

        # Separate caches keyed by asset
        self._hl_prices: dict[str, PriceEntry] = {}
        self._pm_prices: dict[str, PriceEntry] = {}

        self._tasks: list[asyncio.Task] = []
        self._running = False

    # ── Public API ────────────────────────────────────────────

    def get_price(
        self,
        asset: str,
        exchange: str,
        session: Session | None = None,
    ) -> Decimal | None:
        """Return the latest price for an asset on an exchange.

        Checks in-memory cache first, falls back to DB query if stale/missing.
        Returns None if no source has data.
        """
        if exchange == "hyperliquid":
            return self._get_hl_price(asset)
        elif exchange == "polymarket":
            return self._get_pm_price(asset, session)
        return None

    def is_stale(self, asset: str, exchange: str) -> bool:
        """Check whether the cached price is stale."""
        if exchange == "hyperliquid":
            entry = self._hl_prices.get(asset)
            threshold = self._staleness_s
        elif exchange == "polymarket":
            entry = self._pm_prices.get(asset)
            threshold = self._pm_staleness_s
        else:
            return True

        if entry is None:
            return True
        return (time.monotonic() - entry.updated_at) > threshold

    def update_price(
        self,
        asset: str,
        exchange: str,
        price: Decimal,
        source: str = "manual",
    ) -> None:
        """Manually inject a price — primarily for testing."""
        entry = PriceEntry(price=price, updated_at=time.monotonic(), source=source)
        if exchange == "hyperliquid":
            self._hl_prices[asset] = entry
        elif exchange == "polymarket":
            self._pm_prices[asset] = entry

    # ── Lifecycle ─────────────────────────────────────────────

    async def start(self) -> None:
        """Start background tasks (HL WebSocket loop)."""
        if self._running:
            return
        self._running = True
        self._tasks.append(asyncio.create_task(self._hl_ws_loop()))
        log.info("price_oracle_started", assets=sorted(self._assets))

    async def stop(self) -> None:
        """Cancel background tasks."""
        self._running = False
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks.clear()
        log.info("price_oracle_stopped")

    # ── Hyperliquid WebSocket ─────────────────────────────────

    async def _hl_ws_loop(self) -> None:
        """Subscribe to allMids on Hyperliquid WS, auto-reconnect on failure."""
        import websockets

        while self._running:
            try:
                log.info("oracle_hl_ws_connecting", url=self._hl_ws_url)
                async with websockets.connect(self._hl_ws_url) as ws:
                    await ws.send(json.dumps({
                        "method": "subscribe",
                        "subscription": {"type": "allMids"},
                    }))
                    log.info("oracle_hl_ws_subscribed")

                    async for raw in ws:
                        if not self._running:
                            break
                        msg = json.loads(raw)
                        if msg.get("channel") == "allMids":
                            self._handle_all_mids(msg.get("data", {}))

            except asyncio.CancelledError:
                break
            except Exception:
                log.exception("oracle_hl_ws_error", reconnect_in=5)
                await asyncio.sleep(5)

    def _handle_all_mids(self, data: dict) -> None:
        """Parse allMids message and update cache for tracked assets.

        Expected format: {"mids": {"BTC": "60123.5", "ETH": "3456.7", ...}}
        """
        mids = data.get("mids", {})
        now = time.monotonic()
        for asset in self._assets:
            mid_str = mids.get(asset)
            if mid_str is not None:
                try:
                    price = Decimal(mid_str)
                    self._hl_prices[asset] = PriceEntry(
                        price=price, updated_at=now, source="ws",
                    )
                except Exception:
                    log.warning("oracle_parse_error", asset=asset, raw=mid_str)

    # ── Internal price lookups ────────────────────────────────

    def _get_hl_price(self, asset: str) -> Decimal | None:
        """Return HL price from cache if fresh, else None."""
        entry = self._hl_prices.get(asset)
        if entry is None:
            return None
        if (time.monotonic() - entry.updated_at) > self._staleness_s:
            return None
        return entry.price

    def _get_pm_price(self, asset: str, session: Session | None) -> Decimal | None:
        """Return PM price from cache if fresh, else try DB fallback."""
        entry = self._pm_prices.get(asset)
        if entry is not None and (time.monotonic() - entry.updated_at) <= self._pm_staleness_s:
            return entry.price

        # DB fallback
        if session is not None:
            price = self._get_pm_price_from_db(session, asset)
            if price is not None:
                self._pm_prices[asset] = PriceEntry(
                    price=price, updated_at=time.monotonic(), source="db",
                )
                return price
        return None

    @staticmethod
    def _get_pm_price_from_db(session: Session, asset: str) -> Decimal | None:
        """Query the latest Polymarket yes_price for an asset."""
        row = (
            session.query(PolymarketMarketRow.yes_price)
            .filter(
                PolymarketMarketRow.asset == asset,
                PolymarketMarketRow.yes_price.isnot(None),
            )
            .order_by(desc(PolymarketMarketRow.ts))
            .limit(1)
            .scalar()
        )
        if row is None:
            return None
        return Decimal(str(row))
