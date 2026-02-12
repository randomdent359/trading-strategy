# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Trading automation system targeting Polymarket (prediction markets) and Hyperliquid (perpetual futures) for BTC, ETH, and SOL. Stages 0–3 of the overhaul are complete and running in production on `anjie`. The system ingests real market data into Postgres, runs 7 pluggable strategies via an orchestrator, and paper-trades with real-price P&L, risk controls, and Kelly criterion sizing.

## Architecture (live)

```
Hyperliquid WS/REST ──→ hyperliquid_collector.py ──→ trading_market_data (Postgres)
Polymarket REST ───────→ polymarket_collector.py ──→ trading_market_data (Postgres)
                                                           │
                                             ┌─────────────┘
                                             ▼
                                  Strategy Orchestrator
                                  (builds MarketSnapshot per asset,
                                   fans out to 7 enabled strategies)
                                             │
                                             ▼
                             trading_signals.signals (Postgres)
                                             │
                                             ▼
                                    Paper Trading Engine
                                    (risk gate → Kelly sizing →
                                     entry/exit/stop-loss/TP/timeout,
                                     mark-to-market every 60s)
                                             │
                                             ▼
                             trading_paper.positions / mark_to_market
                                             │
                                             ▼
                                  FastAPI backend → React dashboard  [Stage 4 — TODO]
```

### Completion Status

- **Stage 0 — Foundations**: COMPLETE. `trading-core` package, Pydantic models, Alembic migrations, `config.yaml`, structlog.
- **Stage 1 — Data Ingestion**: COMPLETE. `hyperliquid_collector` (WebSocket + REST), `polymarket_collector`, writing to Postgres.
- **Stage 2 — Strategy Framework**: COMPLETE. `Strategy` ABC, decorator registry, 7 strategies (4 ported + 3 new).
- **Stage 3 — Paper Engine**: COMPLETE. Real-price P&L, risk controls (position limits, exposure cap, daily loss pause, cooldown), Kelly criterion sizing, MTM snapshots. Slippage/fee simulation is the remaining TODO.
- **Stage 4 — Dashboard**: TODO. FastAPI backend + React frontend.
- **Stage 5 — Plugin DX**: TODO. Strategy template generator, backtest harness.

## Legacy Code (still running alongside)

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

## Infrastructure

### Hosts

- **anjie** (`10.3.101.5`, user `rdent`) — runs all services via systemd
- **benjy** (`10.6.0.146`) — Postgres host, accessed via mTLS

### Database

- Connection uses SSL client certs, configured via `TRADING_DATABASE_URL` env var in systemd service files
- `psql` is available on anjie for ad-hoc DB queries
- Schemas: `trading_market_data`, `trading_signals`, `trading_paper`

### Deployment

```bash
./deploy/deploy.sh    # Syncs code, installs package, runs migrations, restarts active services
```

- Deploy does NOT overwrite `~/trading/config.yaml` on anjie if it already exists (only copies `config.yaml.example` as a fallback)
- To apply config changes in production, SSH in and edit `~/trading/config.yaml` directly, then restart the relevant service

### Running tests

```bash
pytest tests/ -v                              # All tests
pytest tests/test_risk.py -v                  # Risk controls + Kelly
pytest tests/test_paper_engine.py -v          # Paper engine lifecycle
```

Tests use in-memory SQLite (no Postgres needed). The `db_session` fixture patches JSONB→JSON and BigInteger→Integer for SQLite compatibility.

### Local development

```bash
pip install -e .    # Editable install — required when adding new subpackages/modules
```

The deploy target uses `pip install --force-reinstall --no-deps .` (non-editable) so new modules are picked up automatically.

## Package Structure (`src/trading_core/`)

```
config/         schema.py (PaperConfig, AppConfig), loader.py
collectors/     hyperliquid.py, polymarket.py
db/             base.py, engine.py, tables/ (market_data, signals, paper)
exchange/       hyperliquid.py, polymarket.py (API clients)
logging/        setup.py (structlog)
migrations/     alembic.ini, env.py, versions/
models/         signal.py, market.py, position.py (Pydantic)
orchestrator/   runner.py, snapshot.py, persistence.py
paper/          engine.py, runner.py, sizing.py, risk.py, pricing.py
strategy/       base.py, registry.py, indicators.py, strategies/ (7 classes)
```

## Key Conventions

- **Alembic for all schema changes** — never raw DDL
- **`config.yaml` is the single source of truth** for thresholds, intervals, asset lists, DB connection (overridable by env vars)
- **Write tests alongside code** — especially strategy `evaluate()` methods and paper engine P&L calculations
- **One orchestrator, many strategies** — don't run N separate processes; one orchestrator builds snapshots and fans out
- **Strategy = Python class, not script** — implement `Strategy` ABC, decorate with `@register`, set `enabled: true` in config

## Key Implementation Details

### Paper Engine

- **Signal consumption**: `consume_signals()` only processes `exchange="hyperliquid"` signals. Polymarket signals are informational only (no price oracle for PM positions yet).
- **Risk gate** (in-memory, resets on restart): daily loss pause → cooldown → max positions/strategy → total exposure cap. Evaluated before every position open.
- **Kelly criterion**: Enabled by default (`kelly_enabled: true`). Half-Kelly (`safety_factor=0.5`). Only reduces size for low-confidence signals; high-confidence signals are capped at `risk_pct`.
- **Position sizing**: `risk_amount = equity * risk_pct; qty = risk_amount / (entry_price * stop_loss_pct)`
- **Price source**: Latest candle close from `trading_market_data.candles` (~5s stale from collector write cycle).

### Gotchas

- `SignalRow.confidence` comes back from Postgres as `Decimal` — cast to `float()` before arithmetic with Python floats
- SQLite test fixtures need JSONB→JSON and BigInteger→Integer column type patching (see `db_session` fixture in tests)

## Key Data Models

```python
# Signal emitted by strategies
Signal(strategy, asset, exchange, direction="LONG"|"SHORT", confidence, entry_price, metadata, ts)

# Snapshot passed to strategies (pre-fetched by orchestrator)
MarketSnapshot  # bundles latest N candles, funding, OI, Polymarket state for one asset
```

## Dependencies

Python 3.12+ with: SQLAlchemy, Alembic, Pydantic, structlog, psycopg (binary), websockets, httpx, PyYAML. See `pyproject.toml` for versions.
