# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Trading automation system targeting Polymarket (prediction markets) and Hyperliquid (perpetual futures) for BTC, ETH, and SOL. Currently a prototype with flat-file monitors and simulated P&L; being overhauled into a Postgres-backed system with real market data, pluggable strategies, and real-price paper trading.

## Current State (legacy — being replaced)

```
Polymarket API ──→ contrarian-monitor.py ──→ consensus-extremes.jsonl ──────┐
                   strength-filtered-monitor.py → strength-filtered-extremes.jsonl ─┤
Hyperliquid API ─→ funding-monitor.py ──→ funding-extremes.jsonl ──────────┤
                   funding-oi-monitor.py ──→ funding-oi-extremes.jsonl ────┤
                                                                           ▼
                                                                   paper-trader.py
                                                                   (simulated trades via coin-flip)
```

Legacy code lives in `scripts/` with systemd services in `systemd/` and deploy scripts in `deploy/`. Do not delete the old monitors until Stage 2 strategies are verified to produce equivalent signals.

## Target Architecture (5-stage overhaul per roadmap.md)

```
Hyperliquid WS/REST ──→ hyperliquid_collector.py ──→ trading_market_data (Postgres)
Polymarket REST ───────→ polymarket_collector.py ──→ trading_market_data (Postgres)
                                                            │
                                              ┌─────────────┘
                                              ▼
                                   Strategy Orchestrator
                                   (builds MarketSnapshot per asset,
                                    fans out to all enabled strategies)
                                              │
                                              ▼
                              trading_signals.signals (Postgres)
                                              │
                                              ▼
                                     Paper Trading Engine
                                     (real-price entry/exit,
                                      stop-loss/take-profit/timeout,
                                      mark-to-market every 60s)
                                              │
                                              ▼
                              trading_paper.positions / mark_to_market
                                              │
                                              ▼
                                   FastAPI backend → React dashboard
```

### Stages

- **Stage 0 — Foundations**: `trading-core` pip-installable package (`src/trading_core/`) with Pydantic models, Alembic migrations, `config.yaml`, structured logging (`structlog`)
- **Stage 1 — Data Ingestion**: Single `hyperliquid_collector.py` (WebSocket + REST) and `polymarket_collector.py` replacing the 4 separate monitors, writing to Postgres
- **Stage 2 — Strategy Framework**: `Strategy` ABC with `evaluate(snapshot) -> Signal | None`, decorator-based registry, port 4 existing strategies + add RSIMeanReversion, FundingArb, MomentumBreakout
- **Stage 3 — Paper Engine**: Real-price P&L (no more coin-flip), position sizing (2% risk), stop-loss/take-profit/timeout exits, slippage/fee simulation, mark-to-market snapshots
- **Stage 4 — Dashboard**: FastAPI backend, React frontend with equity curves, strategy comparison, trade explorer, live positions
- **Stage 5 — Plugin DX**: Strategy template generator, backtest harness, optional hot-reload and parameter optimisation

### Postgres Schemas (on host `benjy`)

- `trading_market_data` — candles, funding_snapshots, polymarket_markets
- `trading_signals` — every signal emitted by every strategy
- `trading_paper` — portfolio, positions, mark_to_market

## Key Conventions for the Overhaul

- **Branch per stage**: `stage-0-foundations`, `stage-1-data`, etc.
- **Alembic for all schema changes** — never raw DDL
- **`config.yaml` is the single source of truth** for thresholds, intervals, asset lists, DB connection (overridable by env vars)
- **Write tests alongside code** — especially strategy `evaluate()` methods and paper engine P&L calculations
- **One orchestrator, many strategies** — don't run N separate processes; one orchestrator builds snapshots and fans out
- **Strategy = Python class, not script** — implement `Strategy` ABC, decorate with `@register`, set `enabled: true` in config

## Key Data Models

```python
# Signal emitted by strategies
Signal(strategy, asset, exchange, direction="LONG"|"SHORT", confidence, entry_price, metadata, ts)

# Snapshot passed to strategies (pre-fetched by orchestrator)
MarketSnapshot  # bundles latest N candles, funding, OI, Polymarket state for one asset
```

## Running (legacy)

```bash
./deploy/deploy.sh        # Deploy to anjie (10.3.101.5) via SSH/SCP
./deploy/start-all.sh     # Start all systemd services
./deploy/stop-all.sh
./deploy/status.sh

# Run individual scripts locally
python3 scripts/polymarket/contrarian-monitor.py
python3 scripts/common/paper-trader.py
```

## Dependencies

Currently Python 3.7+ stdlib only + `curl`. The overhaul will introduce: SQLAlchemy, Alembic, Pydantic, structlog, FastAPI, uvicorn, psycopg2/asyncpg, websockets.
