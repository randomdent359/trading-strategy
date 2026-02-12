"""Paper engine runner — async loop that consumes signals and manages positions."""

from __future__ import annotations

import asyncio
import time

from datetime import datetime, timezone

import structlog

from trading_core.config.loader import load_config
from trading_core.config.schema import AppConfig
from trading_core.db.engine import get_session, init_engine
from trading_core.logging.setup import setup_logging
from trading_core.paper.engine import PaperEngine

log = structlog.get_logger("paper_runner")


async def run_loop(config: AppConfig) -> None:
    """Main paper engine loop — consume signals, check exits, write MTM."""
    init_engine(config.database.url)

    # Ensure portfolio exists
    session_gen = get_session()
    session = next(session_gen)
    try:
        portfolio_id = PaperEngine.ensure_portfolio(
            session,
            name="default",
            initial_capital=config.paper.initial_capital,
        )
    finally:
        try:
            next(session_gen)
        except StopIteration:
            pass

    engine = PaperEngine(config.paper, portfolio_id)
    log.info("paper_engine_started", portfolio_id=portfolio_id)

    tick_interval = 5  # seconds between ticks
    mtm_interval = 60  # seconds between mark-to-market snapshots
    last_mtm = time.monotonic()

    while True:
        try:
            session_gen = get_session()
            session = next(session_gen)
            try:
                now = datetime.now(timezone.utc)

                # Consume new signals and open positions
                signals = engine.consume_signals(session)
                for signal in signals:
                    equity = engine.get_current_equity(session)
                    engine.open_position(session, signal, equity)

                # Check exit conditions on open positions
                engine.check_exits(session, now)

                # Write mark-to-market snapshot every 60s
                if time.monotonic() - last_mtm >= mtm_interval:
                    engine.write_mark_to_market(session, now)
                    last_mtm = time.monotonic()

            finally:
                try:
                    next(session_gen)
                except StopIteration:
                    pass

        except Exception:
            log.exception("tick_error")

        await asyncio.sleep(tick_interval)


def main(config_path: str | None = None) -> None:
    """Entry point — load config, set up logging, run the async loop."""
    config = load_config(config_path)
    setup_logging(level=config.logging.level, log_format=config.logging.format)
    asyncio.run(run_loop(config))
