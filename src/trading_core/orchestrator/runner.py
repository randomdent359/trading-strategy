"""Orchestrator runner — main async loop that evaluates strategies on a tick."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any

import structlog

from trading_core.config.loader import load_config
from trading_core.config.schema import AppConfig
from trading_core.db.engine import get_session, init_engine
from trading_core.logging.setup import setup_logging
from trading_core.orchestrator.persistence import persist_signal
from trading_core.orchestrator.snapshot import build_snapshot
from trading_core.strategy import STRATEGY_REGISTRY, Strategy

# Ensure all strategy modules are imported so @register fires
import trading_core.strategy.strategies  # noqa: F401

log = structlog.get_logger("orchestrator")

# Map interval strings to seconds
_INTERVAL_SECONDS = {
    "1m": 60,
    "5m": 300,
    "10m": 600,
    "15m": 900,
    "1h": 3600,
}


def _instantiate_strategies(config: AppConfig) -> list[Strategy]:
    """Build strategy instances from config, filtering to enabled ones."""
    instances: list[Strategy] = []
    for name, strat_conf in config.strategies.items():
        if not strat_conf.enabled:
            log.info("strategy_disabled", strategy=name)
            continue
        cls = STRATEGY_REGISTRY.get(name)
        if cls is None:
            log.warning("strategy_not_found", strategy=name)
            continue
        params: dict[str, Any] = dict(strat_conf.params)
        instance = cls(**params)
        instances.append(instance)
        log.info("strategy_loaded", strategy=name, params=params)
    return instances


def _should_evaluate(
    strategy: Strategy,
    asset: str,
    last_evaluated: dict[str, float],
) -> bool:
    """Check if enough time has elapsed since last evaluation."""
    key = f"{strategy.name}:{asset}"
    now = time.monotonic()
    interval_s = _INTERVAL_SECONDS.get(strategy.interval, 60)
    last = last_evaluated.get(key, 0.0)
    if now - last < interval_s:
        return False
    last_evaluated[key] = now
    return True


async def run_loop(config: AppConfig) -> None:
    """Main orchestrator loop — build snapshots, evaluate, persist signals."""
    init_engine(config.database.url)
    strategies = _instantiate_strategies(config)

    if not strategies:
        log.error("no_strategies_enabled")
        return

    log.info(
        "orchestrator_started",
        strategies=[s.name for s in strategies],
        assets=config.assets,
    )

    last_evaluated: dict[str, float] = {}
    tick_interval = 5  # seconds between orchestrator ticks

    while True:
        try:
            session_gen = get_session()
            session = next(session_gen)
            try:
                for asset in config.assets:
                    snapshot = build_snapshot(session, asset)

                    for strategy in strategies:
                        if asset not in strategy.assets:
                            continue
                        if not _should_evaluate(strategy, asset, last_evaluated):
                            continue

                        try:
                            signal = strategy.evaluate(snapshot)
                        except Exception:
                            log.exception(
                                "strategy_error",
                                strategy=strategy.name,
                                asset=asset,
                            )
                            continue

                        if signal is not None:
                            row_id = persist_signal(session, signal)
                            log.info(
                                "signal_emitted",
                                strategy=signal.strategy,
                                asset=signal.asset,
                                direction=signal.direction,
                                confidence=signal.confidence,
                                signal_id=row_id,
                            )
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
