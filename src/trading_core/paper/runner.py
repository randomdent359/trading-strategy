"""Paper engine runner — async loop that consumes signals and manages positions."""

from __future__ import annotations

import asyncio
import time

from datetime import datetime, timezone

import structlog

from trading_core.config.loader import load_config
from trading_core.config.schema import AppConfig
from trading_core.db.engine import get_session, init_engine
from trading_core.db.tables.accounts import AccountRow
from trading_core.logging.setup import setup_logging
from trading_core.paper.engine import PaperEngine
from trading_core.paper.oracle import PriceOracle
from trading_core.strategy import STRATEGY_REGISTRY
import trading_core.strategy.strategies  # noqa: F401 — trigger @register decorators

log = structlog.get_logger("paper_runner")


def bootstrap_accounts(session, config: AppConfig) -> list[AccountRow]:
    """Auto-create one account per enabled strategy × exchange from config.

    Capital is split evenly from config.paper.initial_capital.
    Returns the newly created AccountRow list.
    """
    enabled_strategies = [
        name for name, cfg in config.strategies.items()
        if cfg.enabled and name in STRATEGY_REGISTRY
    ]
    if not enabled_strategies:
        log.warning("no_enabled_strategies_for_bootstrap")
        return []

    # Collect (exchange, strategy) pairs from strategy class metadata
    pairs = []
    for name in enabled_strategies:
        cls = STRATEGY_REGISTRY[name]
        for exchange in getattr(cls, "exchanges", ["hyperliquid"]):
            pairs.append((exchange, name))

    if not pairs:
        return []

    per_account_capital = config.paper.initial_capital / len(pairs)
    created = []
    for exchange, strategy in pairs:
        account_name = f"{strategy}_{exchange}"
        aid = PaperEngine.ensure_account(
            session,
            name=account_name,
            exchange=exchange,
            strategy=strategy,
            initial_capital=per_account_capital,
        )
        row = session.get(AccountRow, aid)
        created.append(row)

    log.info("accounts_bootstrapped", count=len(created),
             names=[a.name for a in created])
    return created


async def run_loop(config: AppConfig) -> None:
    """Main paper engine loop — one engine per active account."""
    init_engine(config.database.url)

    # Load active accounts (or bootstrap)
    session_gen = get_session()
    session = next(session_gen)
    try:
        accounts = session.query(AccountRow).filter(AccountRow.active == True).all()  # noqa: E712
        if not accounts:
            accounts = bootstrap_accounts(session, config)
    finally:
        try:
            next(session_gen)
        except StopIteration:
            pass

    if not accounts:
        log.error("no_accounts_available")
        return

    # Start shared price oracle if enabled
    oracle: PriceOracle | None = None
    if config.paper.price_oracle_enabled:
        hl_cfg = config.exchanges.get("hyperliquid")
        ws_url = (
            hl_cfg.base_url.replace("https://", "wss://").replace("http://", "ws://") + "/ws"
            if hl_cfg
            else "wss://api.hyperliquid.xyz/ws"
        )
        oracle = PriceOracle(
            assets=config.assets,
            hl_ws_url=ws_url,
            staleness_threshold_s=config.paper.price_oracle_staleness_s,
            pm_staleness_threshold_s=config.paper.price_oracle_pm_staleness_s,
        )
        await oracle.start()

    # Create one engine per active account
    engines: list[PaperEngine] = []
    for acct in accounts:
        engine = PaperEngine(
            config=config.paper,
            account_id=acct.id,
            account_exchange=acct.exchange,
            account_strategy=acct.strategy,
            oracle=oracle,
        )
        engines.append(engine)
        log.info("engine_created", account_id=acct.id, name=acct.name,
                 exchange=acct.exchange, strategy=acct.strategy)

    log.info("paper_engine_started", num_engines=len(engines), oracle_enabled=oracle is not None)

    tick_interval = 5  # seconds between ticks
    mtm_interval = 60  # seconds between mark-to-market snapshots
    last_mtm = time.monotonic()

    while True:
        try:
            session_gen = get_session()
            session = next(session_gen)
            try:
                now = datetime.now(timezone.utc)

                # Per-engine signal consumption and position opening
                for engine in engines:
                    signals = engine.consume_signals(session)
                    for signal in signals:
                        equity = engine.get_current_equity(session)
                        verdict = engine.check_risk(session, signal, equity, now)
                        if verdict.allowed:
                            engine.open_position(session, signal, equity)
                        else:
                            log.info(
                                "signal_rejected",
                                account_id=engine.account_id,
                                strategy=signal.strategy,
                                asset=signal.asset,
                                reason=verdict.reason,
                            )

                    # Check exit conditions on this engine's open positions
                    engine.check_exits(session, now)

                # Write mark-to-market snapshot every 60s
                if time.monotonic() - last_mtm >= mtm_interval:
                    for engine in engines:
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
