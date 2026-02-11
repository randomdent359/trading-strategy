# Trading System Implementation Plan

## Current State Assessment

### `trading-strategy` repo
- 4 monitor scripts polling Polymarket and Hyperliquid APIs on fixed intervals
- Each writes alerts to `.jsonl` flat files (consensus extremes, funding rate extremes, etc.)
- 1 paper trader that polls those alert files every 2s, simulates entries/exits with hardcoded win-rate randomisation, writes to `trades.jsonl` and `metrics.json`
- Deployment via systemd services to a single host (`anjie`)
- **No real market data used for exits** — trades are resolved by coin-flip weighted to target win rates
- **No actual price tracking** — no candle/tick data captured
- **No database** — everything is flat files
- Only contrarian strategies; no technical or momentum strategies
- Scoped only to "extremes" detection, not BTC/ETH/SOL spot or perp price action

### `trading-dashboard` repo
- React + TypeScript + Vite frontend
- Express `server.js` backend that reads flat files from the `anjie` host
- Displays P&L, win rate, trade count per strategy
- No historical charting, no per-asset breakdown, no strategy comparison over time

---

## Target End State

A system that:
1. Continuously ingests real market data (price, orderbook, funding, OI) for BTC, ETH, SOL from Hyperliquid and Polymarket
2. Runs a growing library of pluggable strategies that emit typed signals (LONG / SHORT / CLOSE / PASS)
3. Executes paper trades against real prices in a local Postgres database
4. Tracks full position lifecycle: entry, mark-to-market, exit, P&L attribution
5. Dashboards strategy-level and asset-level profitability with time-series visualisation
6. Makes it trivial to add a new strategy (write one Python class, register it, done)

---

## Stage 0 — Foundations (prerequisite refactor)

**Goal:** Establish the shared infrastructure that every later stage depends on.

### 0.1 Monorepo or shared package
Decide whether to merge both repos or keep them separate with a shared `trading-core` Python package. Recommendation: keep two repos but create a `trading-core` pip-installable package (can live in `trading-strategy` under `src/trading_core/`) that both repos depend on. This package will hold:
- Data models / Pydantic schemas (Signal, Position, Trade, OHLCV, etc.)
- Database connection and migration utilities
- Strategy base class and registry
- Exchange client wrappers

### 0.2 Postgres setup
verify access to Postgres on `benjy`. Create three schemas:

```
trading_market_data   — candles, ticks, funding snapshots, OI snapshots
trading_signals       — every signal emitted by every strategy
trading_paper         — positions, trades, daily P&L, strategy metadata
```

Migration tool: Alembic (SQLAlchemy-based). Every schema change is a versioned migration.

### 0.3 Configuration
Replace hardcoded values (poll intervals, thresholds, asset list, DB connection) with a single `config.yaml` (or TOML) loaded at startup, overridable by env vars. Structure:

```yaml
assets: [BTC, ETH, SOL]
exchanges:
  hyperliquid:
    base_url: https://api.hyperliquid.xyz
    poll_interval_s: 5
  polymarket:
    base_url: https://clob.polymarket.com
    poll_interval_s: 10
database:
  url: postgresql://trading:***@localhost:5432/trading
strategies:
  contrarian_pure:
    enabled: true
    params:
      threshold: 0.72
```

### 0.4 Logging and observability
Replace print/file logging with structured logging (Python `structlog`). Every log line is JSON with strategy name, asset, timestamp. Later stages can ship these to the dashboard.

**Deliverables:** `trading-core` package skeleton, Alembic migrations for all three schemas, `config.yaml` template, structured logging wired up.

---

## Stage 1 — Real Market Data Ingestion

**Goal:** Continuously capture real price, funding, and OI data into Postgres so strategies can query it.

### 1.1 Hyperliquid data collector
A single long-running process (replacing the four separate monitors) that:
- Subscribes to Hyperliquid WebSocket for real-time trades/candles for BTC, ETH, SOL perps
- Polls REST endpoints every 60s for funding rate and open interest snapshots
- Writes 1m OHLCV candles to `trading_market_data.candles`
- Writes funding/OI snapshots to `trading_market_data.funding_snapshots`

Schema:
```sql
CREATE TABLE trading_market_data.candles (
    id            BIGSERIAL PRIMARY KEY,
    exchange      TEXT NOT NULL,        -- 'hyperliquid' | 'polymarket'
    asset         TEXT NOT NULL,        -- 'BTC' | 'ETH' | 'SOL'
    interval      TEXT NOT NULL,        -- '1m' | '5m' | '1h'
    open_time     TIMESTAMPTZ NOT NULL,
    open          NUMERIC NOT NULL,
    high          NUMERIC NOT NULL,
    low           NUMERIC NOT NULL,
    close         NUMERIC NOT NULL,
    volume        NUMERIC NOT NULL,
    UNIQUE(exchange, asset, interval, open_time)
);

CREATE TABLE trading_market_data.funding_snapshots (
    id            BIGSERIAL PRIMARY KEY,
    exchange      TEXT NOT NULL,
    asset         TEXT NOT NULL,
    ts            TIMESTAMPTZ NOT NULL,
    funding_rate  NUMERIC NOT NULL,
    open_interest NUMERIC,
    mark_price    NUMERIC,
    UNIQUE(exchange, asset, ts)
);
```

### 1.2 Polymarket data collector
- Poll CLOB API for BTC/ETH/SOL related prediction markets (15-min and longer timeframes)
- Capture orderbook snapshots and consensus probabilities
- Write to `trading_market_data.polymarket_markets`

```sql
CREATE TABLE trading_market_data.polymarket_markets (
    id              BIGSERIAL PRIMARY KEY,
    market_id       TEXT NOT NULL,
    market_title    TEXT NOT NULL,
    asset           TEXT NOT NULL,
    ts              TIMESTAMPTZ NOT NULL,
    yes_price       NUMERIC,
    no_price        NUMERIC,
    volume_24h      NUMERIC,
    liquidity       NUMERIC,
    UNIQUE(market_id, ts)
);
```

### 1.3 Data quality
- Add a watchdog: if no candle arrives for 5 minutes, log a warning and attempt reconnect
- Deduplicate on unique constraints; use `ON CONFLICT DO NOTHING`
- Backfill: on first startup, pull last 24h of 1m candles via REST

**Deliverables:** `hyperliquid_collector.py`, `polymarket_collector.py`, corresponding systemd services, verified data flowing into Postgres.

---

## Stage 2 — Strategy Framework and Signal Generation

**Goal:** A pluggable strategy framework where each strategy is a Python class that receives market data and emits signals.

### 2.1 Strategy base class

```python
from abc import ABC, abstractmethod
from trading_core.models import Signal, MarketSnapshot

class Strategy(ABC):
    name: str                    # unique identifier
    assets: list[str]            # which assets this strategy trades
    exchanges: list[str]         # which exchanges it needs data from
    interval: str                # how often it should be evaluated ('1m', '5m', etc.)

    @abstractmethod
    def evaluate(self, snapshot: MarketSnapshot) -> Signal | None:
        """Return a Signal(direction, confidence, metadata) or None to pass."""
        ...
```

`MarketSnapshot` is a dataclass bundling the latest N candles, current funding, OI, Polymarket state for a given asset — pre-fetched by the orchestrator so strategies don't each hit the DB.

`Signal` is:
```python
@dataclass
class Signal:
    strategy: str
    asset: str
    exchange: str
    direction: Literal["LONG", "SHORT"]
    confidence: float            # 0.0–1.0
    entry_price: Decimal         # current mark price at signal time
    metadata: dict               # strategy-specific context
    ts: datetime
```

### 2.2 Strategy registry
A simple dict-based registry populated at startup from config:

```python
STRATEGY_REGISTRY: dict[str, type[Strategy]] = {}

def register(cls):
    STRATEGY_REGISTRY[cls.name] = cls
    return cls
```

Config determines which are `enabled: true`. Adding a new strategy = write the class, decorate with `@register`, set `enabled: true` in config.

### 2.3 Migrate existing strategies
Port the four existing monitors into this framework:

| Old script | New class | Key params |
|---|---|---|
| `contrarian-monitor.py` | `ContrarianPure` | threshold=0.72 |
| `strength-filtered-monitor.py` | `ContrarianStrength` | threshold=0.80 |
| `funding-monitor.py` | `FundingRate` | threshold=0.0012 |
| `funding-oi-monitor.py` | `FundingOI` | funding=0.0015, oi_pct=85 |

### 2.4 Add initial new strategies
To prove the framework and cover BTC/ETH/SOL price action:

| Strategy | Logic | Data needed |
|---|---|---|
| `RSIMeanReversion` | RSI(14) on 5m candles > 75 → SHORT, < 25 → LONG | 5m candles |
| `FundingArb` | Funding > 0.05% → SHORT perp (market pays you); < -0.05% → LONG | Funding snapshots |
| `MomentumBreakout` | Price breaks 1h Bollinger Band (2σ) with volume spike | 1m + 1h candles |

### 2.5 Signal persistence
Every signal (including passes) written to `trading_signals.signals`:

```sql
CREATE TABLE trading_signals.signals (
    id          BIGSERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL,
    strategy    TEXT NOT NULL,
    asset       TEXT NOT NULL,
    exchange    TEXT NOT NULL,
    direction   TEXT,              -- NULL if PASS
    confidence  NUMERIC,
    entry_price NUMERIC,
    metadata    JSONB,
    acted_on    BOOLEAN DEFAULT FALSE  -- did the paper engine take a position?
);
```

### 2.6 Strategy orchestrator
A single process that:
1. On each tick (configurable, default 5s), builds a `MarketSnapshot` per asset from the DB
2. Calls `evaluate()` on every enabled strategy
3. Writes resulting signals to `trading_signals.signals`
4. Publishes signals to an in-process event bus (or Postgres NOTIFY) for the paper engine

**Deliverables:** `Strategy` ABC, registry, 4 ported strategies + 3 new ones, orchestrator process, signals table populated.

---

## Stage 3 — Paper Trading Engine

**Goal:** Consume signals and manage a realistic paper portfolio in Postgres with proper position tracking.

### 3.1 Core schema

```sql
-- Portfolio-level config
CREATE TABLE trading_paper.portfolio (
    id              SERIAL PRIMARY KEY,
    name            TEXT UNIQUE NOT NULL,       -- 'default'
    initial_capital NUMERIC NOT NULL DEFAULT 10000,
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- Open and closed positions
CREATE TABLE trading_paper.positions (
    id              BIGSERIAL PRIMARY KEY,
    portfolio_id    INT REFERENCES trading_paper.portfolio(id),
    strategy        TEXT NOT NULL,
    asset           TEXT NOT NULL,
    exchange        TEXT NOT NULL,
    direction       TEXT NOT NULL,              -- 'LONG' | 'SHORT'
    entry_price     NUMERIC NOT NULL,
    entry_ts        TIMESTAMPTZ NOT NULL,
    quantity        NUMERIC NOT NULL,           -- in asset units
    exit_price      NUMERIC,
    exit_ts         TIMESTAMPTZ,
    exit_reason     TEXT,                       -- 'signal' | 'stop_loss' | 'take_profit' | 'timeout'
    realised_pnl    NUMERIC,
    status          TEXT NOT NULL DEFAULT 'OPEN', -- 'OPEN' | 'CLOSED'
    signal_id       BIGINT REFERENCES trading_signals.signals(id),
    metadata        JSONB
);

-- Mark-to-market snapshots (for equity curves)
CREATE TABLE trading_paper.mark_to_market (
    id              BIGSERIAL PRIMARY KEY,
    portfolio_id    INT REFERENCES trading_paper.portfolio(id),
    ts              TIMESTAMPTZ NOT NULL,
    total_equity    NUMERIC NOT NULL,
    unrealised_pnl  NUMERIC NOT NULL,
    realised_pnl    NUMERIC NOT NULL,
    open_positions  INT NOT NULL,
    breakdown       JSONB                      -- per-strategy and per-asset detail
);
```

### 3.2 Paper engine process
Replaces the current `paper-trader.py`. Responsibilities:

1. **Signal consumer:** Listens for new signals (via Postgres NOTIFY or polling `trading_signals.signals` for `acted_on = FALSE`)
2. **Position sizing:** Fixed fractional — risk 2% of current equity per trade (configurable)
3. **Entry:** On a LONG/SHORT signal with confidence above threshold, open a position at the signal's `entry_price` (which is the real mark price at signal time)
4. **Mark-to-market:** Every 60s, fetch current prices from `trading_market_data.candles`, update unrealised P&L, write to `mark_to_market`
5. **Exit rules** (evaluated every tick):
   - Stop loss: configurable per strategy (default 2%)
   - Take profit: configurable per strategy (default 4%)
   - Timeout: close after N minutes if neither hit (configurable, default 60m)
   - Opposing signal: if the same strategy emits a signal in the opposite direction, close and reverse
6. **On exit:** Calculate realised P&L from real entry and exit prices, update position status, write to DB
7. **No simulated randomness** — P&L is entirely determined by real price movement between entry and exit

### 3.3 Risk controls
- Max concurrent positions per strategy (default 3)
- Max total exposure as % of equity (default 50%)
- Max loss per day per strategy — pause strategy for rest of day if hit
- Cooldown period after a loss (configurable, default 5 minutes)

### 3.4 Slippage and fee simulation
- Apply configurable slippage to entry and exit prices (default 0.05% for Hyperliquid, 0.5% for Polymarket)
- Deduct trading fees from P&L (Hyperliquid: ~0.02% maker / 0.05% taker; Polymarket: variable)

**Deliverables:** Paper engine process, positions flowing through full lifecycle with real-price P&L, mark-to-market snapshots populating every minute.

---

## Stage 4 — Dashboard: Strategy Evaluation and Visualisation

**Goal:** Extend the dashboard to show whether each strategy is making or losing money, with enough depth to decide which to keep, tune, or kill.

### 4.1 Backend API (extend `server.js` or migrate to FastAPI)
Given the rest of the system is Python + Postgres, recommendation: add a lightweight FastAPI backend alongside or replacing the Express server. Endpoints:

| Endpoint | Returns |
|---|---|
| `GET /api/strategies` | List of all strategies with current status, total P&L, win rate, Sharpe |
| `GET /api/strategies/{name}/signals` | Paginated signal history |
| `GET /api/strategies/{name}/trades` | Paginated trade history with entry/exit prices |
| `GET /api/equity-curve?strategy=X&asset=Y&from=&to=` | Time-series equity data for charting |
| `GET /api/positions/open` | Currently open positions with unrealised P&L |
| `GET /api/assets/{asset}/performance` | Per-asset P&L across all strategies |
| `GET /api/summary` | Portfolio-level metrics: total equity, drawdown, Sharpe, Sortino |

### 4.2 Frontend views

**Strategy Comparison (home page):**
- Table: strategy name, # trades, win rate, avg win, avg loss, profit factor, Sharpe ratio, total P&L
- Sortable and filterable by asset, exchange, time range
- Colour-coded rows (green = profitable, red = losing)

**Equity Curve:**
- Line chart (Recharts) showing equity over time
- Overlays: one line per strategy, plus a portfolio-total line
- Toggleable per strategy / per asset
- Drawdown subplot

**Trade Explorer:**
- Filterable table of all closed trades
- Click a trade → detail view showing entry/exit on a price chart (candle chart with markers)

**Live Positions:**
- Table of open positions with real-time unrealised P&L
- Auto-refresh every 10s

**Strategy Health:**
- Per-strategy cards showing: last signal time, signals/hour, positions/day, current drawdown
- Alert indicators if a strategy has gone silent or hit its daily loss limit

### 4.3 Key metrics to compute

| Metric | Formula |
|---|---|
| Win rate | wins / total trades |
| Profit factor | gross profit / gross loss |
| Sharpe ratio | mean(daily returns) / std(daily returns) × √252 |
| Sortino ratio | mean(daily returns) / downside_std × √252 |
| Max drawdown | max peak-to-trough decline in equity curve |
| Avg hold time | mean(exit_ts - entry_ts) |
| Expectancy | (win_rate × avg_win) - (loss_rate × avg_loss) |

Compute these server-side on each API call (or cache with 60s TTL).

**Deliverables:** FastAPI backend with all endpoints, React dashboard with the views above, live auto-refresh.

---

## Stage 5 — Strategy Plugin System and Developer Experience

**Goal:** Make it dead-simple for you (or an LLM agent) to add a new strategy.

### 5.1 Strategy template generator

```bash
python -m trading_core new-strategy --name "VWAPReversion" --assets BTC,ETH,SOL --interval 5m
```

Generates:
```
strategies/
  vwap_reversion/
    __init__.py          # @register class
    strategy.py          # evaluate() stub
    config.yaml          # default params
    tests/
      test_strategy.py   # pytest stub with sample data
```

### 5.2 Backtesting harness
Before a strategy goes live in paper trading, you should be able to test it against historical data in the DB:

```bash
python -m trading_core backtest --strategy VWAPReversion --from 2026-01-01 --to 2026-02-10
```

Outputs: total P&L, win rate, Sharpe, equity curve plot, and writes results to `trading_paper.backtest_runs` for dashboard comparison.

### 5.3 Hot-reload (nice-to-have)
The strategy orchestrator watches the `strategies/` directory. When a file changes, it reloads that strategy module without restarting the whole system. Use `importlib.reload()` with error handling.

### 5.4 Strategy parameter optimisation (nice-to-have)
A simple grid search / random search over strategy params using the backtest harness:

```bash
python -m trading_core optimise --strategy FundingRate \
    --param threshold=0.05:0.20:0.01 \
    --param timeout_m=30:120:15 \
    --metric sharpe
```

### 5.5 Documentation
Each strategy class should have a docstring explaining the thesis, the expected edge, the data requirements, and the risk characteristics. The dashboard should render this on the strategy detail page.

**Deliverables:** Template generator, backtest harness, optional hot-reload, strategy docs rendered in dashboard.

---

## Implementation Order and Rough Effort

| Stage | Description | Depends on | Rough effort |
|---|---|---|---|
| **0** | Foundations (package, Postgres, config, logging) | — | 3–4 days |
| **1** | Market data ingestion | Stage 0 | 3–4 days |
| **2** | Strategy framework + signal generation | Stage 0, 1 | 4–5 days |
| **3** | Paper trading engine | Stage 1, 2 | 4–5 days |
| **4** | Dashboard visualisation | Stage 3 | 5–7 days |
| **5** | Plugin system and DX | Stage 2, 3 | 3–4 days |

Stages 0–3 are the critical path. Stage 4 can begin in parallel once Stage 3 is producing data. Stage 5 can be done incrementally.

**Total estimate: ~3–4 weeks of focused work** (one person or one LLM agent session per stage).

---

## Key Architectural Decisions

1. **Postgres over flat files.** JSONL doesn't support queries, joins, time-range aggregation, or concurrent access. Postgres gives you all of these plus NOTIFY for event-driven patterns.

2. **Real prices for paper P&L.** The current system's randomised win/loss tells you nothing about whether a strategy works. Every paper trade must use the actual market price at entry and exit.

3. **One orchestrator, many strategies.** Don't run N separate monitor processes. One orchestrator builds snapshots and fans out to strategies. Easier to manage, share data, and avoid rate-limit issues.

4. **FastAPI over Express for the backend.** The data and strategies are Python. Having the API server in Python too means you can import the same models and query logic directly. The React frontend doesn't care what serves its JSON.

5. **Strategy as a class, not a script.** A class with a defined interface can be tested, backtested, registered, and managed uniformly. A standalone script can't.

---

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Hyperliquid/Polymarket API rate limits | Respect documented limits; use WebSocket where available; centralise all API calls in collectors, not strategies |
| Postgres becomes a bottleneck with 1m candle writes | Partition `candles` table by month; only keep 30 days of 1m data, aggregate to 1h/1d for older data |
| Strategy bugs cause phantom P&L | Every signal and position change is immutably logged; dashboard shows raw data; add sanity checks (e.g., P&L > 50% in one trade = flag) |
| Overfitting during parameter optimisation | Use walk-forward validation (optimise on first 70% of data, validate on last 30%); track in-sample vs out-of-sample metrics |
| Dashboard becomes stale if a service dies | Add health check endpoint per service; dashboard shows "last heartbeat" per component; systemd auto-restarts |

---

## Notes for the OpenClaw / Claude Code Agent

When working through these stages:

- **Start each stage by creating a branch** (`stage-0-foundations`, `stage-1-data`, etc.)
- **Write tests alongside code** — especially for the strategy `evaluate()` methods and paper engine P&L calculations
- **Use Alembic for every schema change** — never raw DDL
- **Keep the config file as the single source of truth** for thresholds, intervals, and feature flags
- **Don't delete the old flat-file monitors until Stage 2 strategies are verified** to produce equivalent signals
- **Commit frequently** with descriptive messages so the history is reviewable
