"""Polymarket data collector — REST polling for prediction markets.

Fetches crypto-related events from the gamma API /events endpoint
using tag-based filtering (crypto-prices, bitcoin, ethereum, solana,
up-or-down), extracts nested markets, and writes snapshots to Postgres.

Run: python -m trading_core.collectors polymarket [--config config.yaml]
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from trading_core.config import load_config
from trading_core.db import init_engine
from trading_core.db.engine import get_session
from trading_core.exchange.polymarket import PolymarketClient
from trading_core.logging import get_logger, setup_logging

log = get_logger(__name__)


def _parse_end_date(raw: str | None) -> datetime | None:
    """Parse an ISO 8601 endDate string from the Polymarket API.

    Returns None for missing or malformed values rather than crashing.
    """
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _upsert_market(session: Session, row: dict) -> None:
    """Insert a polymarket market snapshot, ignoring duplicates."""
    session.execute(
        text("""
            INSERT INTO trading_market_data.polymarket_markets
                (market_id, market_title, asset, ts, yes_price, no_price, volume_24h, liquidity, end_date)
            VALUES (:market_id, :market_title, :asset, :ts, :yes_price, :no_price, :volume_24h, :liquidity, :end_date)
            ON CONFLICT (market_id, ts) DO NOTHING
        """),
        row,
    )
    session.commit()


def _extract_markets(market_data: list[dict], assets: list[str]) -> list[dict]:
    """Filter and transform market dicts into DB-ready rows.

    Accepts the flat list of market dicts returned by get_crypto_markets()
    (already extracted from /events responses and deduplicated).
    """
    rows: list[dict] = []
    ts = datetime.now(timezone.utc)

    for market in market_data:
        if not isinstance(market, dict):
            continue

        title = market.get("question", "") or market.get("title", "")
        if not title:
            continue

        asset = PolymarketClient.classify_asset(title)
        if asset is None or asset not in assets:
            continue

        prices = PolymarketClient.parse_outcome_prices(market.get("outcomePrices", []))
        yes_price = prices[0] if len(prices) > 0 else None
        no_price = prices[1] if len(prices) > 1 else None

        market_id = market.get("conditionId", "") or market.get("condition_id", "")
        if not market_id:
            continue

        rows.append({
            "market_id": str(market_id),
            "market_title": title[:500],
            "asset": asset,
            "ts": ts,
            "yes_price": yes_price,
            "no_price": no_price,
            "volume_24h": market.get("volume24hr") or market.get("volume"),
            "liquidity": market.get("liquidity"),
            "end_date": _parse_end_date(market.get("endDate")),
        })

    return rows


async def poll_markets(
    client: PolymarketClient,
    session: Session,
    assets: list[str],
    interval_s: int = 600,
) -> None:
    """Poll Polymarket for crypto-related prediction markets."""
    while True:
        try:
            log.info("polling polymarket events by tag")
            market_data = await client.get_crypto_markets()
            rows = _extract_markets(market_data, assets)

            for row in rows:
                _upsert_market(session, row)

            log.info("polymarket poll complete", markets_found=len(rows), total_fetched=len(market_data))

        except Exception:
            session.rollback()
            log.exception("polymarket poll failed")

        await asyncio.sleep(interval_s)


async def run(config_path: str | None = None) -> None:
    """Main entry point — poll Polymarket on a loop."""
    cfg = load_config(config_path)
    setup_logging(level=cfg.logging.level, log_format=cfg.logging.format)

    engine = init_engine(cfg.database.url)
    session_gen = get_session()
    session = next(session_gen)

    pm_cfg = cfg.exchanges.get("polymarket")
    base_url = pm_cfg.base_url if pm_cfg else "https://gamma-api.polymarket.com"
    poll_interval = pm_cfg.poll_interval_s if pm_cfg else 600

    client = PolymarketClient(base_url=base_url)
    assets = cfg.assets

    log.info("starting polymarket collector", assets=assets)

    try:
        await poll_markets(client, session, assets, interval_s=poll_interval)
    finally:
        session.close()
        await client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Polymarket data collector")
    parser.add_argument("--config", default="config.yaml", help="Path to config file")
    args = parser.parse_args()
    asyncio.run(run(args.config))


if __name__ == "__main__":
    main()
