# Trading Dashboard API

Base URL: `http://<host>:8000`

All responses are JSON. Timestamps are ISO 8601 UTC. Monetary values are floats (USD-equivalent for crypto, raw for Polymarket).

---

## Domain Model

### Account

An **account** is the fundamental unit of capital allocation. Each account has:

- A **unique name** (human identifier, e.g. `"funding_rate_hyperliquid"`)
- Exactly one **exchange** (`"hyperliquid"` or `"polymarket"`)
- Exactly one **strategy** (e.g. `"funding_rate"`, `"rsi_mean_reversion"`)
- Its own **initial capital** and tracked **equity** over time
- An **active** flag — inactive accounts stop consuming signals

Accounts own all positions and mark-to-market snapshots. Two accounts can run the same strategy on the same exchange (useful for A/B testing different capital allocations) as long as they have different names.

**Key rule:** one account = one strategy + one exchange + own capital. The paper engine creates one engine instance per active account and each engine only consumes signals matching its (exchange, strategy) pair.

### Portfolio

A **portfolio** is a named grouping of accounts. It exists purely for aggregation — viewing combined equity, P&L, and metrics across multiple accounts.

- Portfolios have a **unique name** and optional **description**
- The relationship is **many-to-many**: an account can belong to multiple portfolios, and a portfolio can contain any number of accounts
- A `"default"` portfolio is auto-created containing all accounts (used by backward-compatible global endpoints)

Portfolios do not own capital. Their equity and P&L are always computed by summing their member accounts.

### Exchange

Currently two exchanges are supported:

| Exchange | Type | Assets | Notes |
|---|---|---|---|
| `hyperliquid` | Perpetual futures | BTC, ETH, SOL | Full paper trading with real price feed |
| `polymarket` | Prediction markets | Various | Signals only (no position execution yet) |

### Strategy

A strategy is a registered Python class that evaluates market data and emits signals. Strategies declare which assets and exchanges they operate on. The system currently has 7 strategies; each is independently enabled/disabled in config.

### Relationships Diagram

```
Portfolio (aggregation view)
  └── has many ──→ Account (capital unit)
                     ├── exchange: "hyperliquid" | "polymarket"
                     ├── strategy: "funding_rate" | "rsi_mean_reversion" | ...
                     ├── has many ──→ Position (trade)
                     └── has many ──→ MarkToMarket (equity snapshot)

Signal (emitted by orchestrator)
  ├── exchange
  ├── strategy
  └── consumed by ──→ matching Account's engine
```

---

## Endpoints

### Health

#### `GET /api/health`

```json
{ "status": "healthy", "timestamp": "2025-06-15T12:00:00+00:00" }
```

---

### Accounts

#### `GET /api/accounts`

List all accounts with latest equity snapshot.

**Response:**

```json
{
  "accounts": [
    {
      "id": 1,
      "name": "funding_rate_hyperliquid",
      "exchange": "hyperliquid",
      "strategy": "funding_rate",
      "initialCapital": 10000.0,
      "active": true,
      "createdAt": "2025-06-01T00:00:00+00:00",
      "currentEquity": 10450.25,
      "unrealisedPnl": 125.50,
      "realisedPnl": 324.75,
      "openPositions": 2
    }
  ]
}
```

| Field | Type | Description |
|---|---|---|
| `id` | int | Account ID |
| `name` | string | Unique human-readable name |
| `exchange` | string | `"hyperliquid"` or `"polymarket"` |
| `strategy` | string | Strategy name |
| `initialCapital` | float | Starting capital |
| `active` | bool | Whether the engine consumes signals for this account |
| `createdAt` | string\|null | ISO 8601 creation timestamp |
| `currentEquity` | float | Latest total equity (falls back to `initialCapital` if no MTM yet) |
| `unrealisedPnl` | float | Current unrealised P&L |
| `realisedPnl` | float | Cumulative realised P&L |
| `openPositions` | int | Number of currently open positions |

---

#### `POST /api/accounts`

Create a new account.

**Request body:**

```json
{
  "name": "rsi_hyperliquid_v2",
  "exchange": "hyperliquid",
  "strategy": "rsi_mean_reversion",
  "initial_capital": 5000
}
```

| Field | Type | Required | Default |
|---|---|---|---|
| `name` | string | yes | — |
| `exchange` | string | yes | — |
| `strategy` | string | yes | — |
| `initial_capital` | float | no | 10000 |

**Response (201):**

```json
{ "id": 3, "name": "rsi_hyperliquid_v2" }
```

**Errors:**
- `409` — name already exists

---

#### `PATCH /api/accounts/{account_id}`

Toggle active status or rename an account.

**Request body** (all fields optional):

```json
{
  "name": "new_name",
  "active": false
}
```

| Field | Type | Description |
|---|---|---|
| `name` | string\|null | New name (must be unique) |
| `active` | bool\|null | Enable/disable signal consumption |

**Response:**

```json
{ "id": 1, "name": "new_name", "active": false }
```

**Errors:**
- `404` — account not found
- `409` — name conflict

---

#### `GET /api/accounts/{account_id}/summary`

Account-level metrics and equity.

**Response:**

```json
{
  "id": 1,
  "name": "funding_rate_hyperliquid",
  "exchange": "hyperliquid",
  "strategy": "funding_rate",
  "initialCapital": 10000.0,
  "currentEquity": 10450.25,
  "unrealisedPnl": 125.50,
  "realisedPnl": 324.75,
  "openPositions": 2,
  "totalTrades": 47,
  "winRate": 63.83,
  "totalPnl": 324.75,
  "profitFactor": 1.85,
  "sharpeRatio": 1.42,
  "sortinoRatio": 2.01,
  "maxDrawdown": 3.25,
  "expectancy": 12.50,
  "avgHoldMinutes": 42.30
}
```

Metrics are cached (60s TTL). See [Metrics Fields](#metrics-fields) for definitions.

**Errors:**
- `404` — account not found

---

#### `GET /api/accounts/{account_id}/positions`

Paginated positions for an account.

**Query params:**

| Param | Type | Default | Description |
|---|---|---|---|
| `status` | string | all | Filter: `"OPEN"` or `"CLOSED"` |
| `limit` | int | 100 | Page size |
| `offset` | int | 0 | Pagination offset |

**Response:**

```json
{
  "positions": [
    {
      "id": 142,
      "strategy": "funding_rate",
      "asset": "BTC",
      "exchange": "hyperliquid",
      "direction": "LONG",
      "entryPrice": 60100.10,
      "entryTime": "2025-06-15T10:30:00+00:00",
      "quantity": 0.0033,
      "exitPrice": 61050.00,
      "exitTime": "2025-06-15T11:15:00+00:00",
      "exitReason": "take_profit",
      "realisedPnl": 3.14,
      "status": "CLOSED",
      "metadata": {
        "raw_price": 60000.0,
        "slippage_pct": 0.001,
        "exit_raw_price": 61000.0,
        "exit_slippage_pct": 0.001,
        "fees": 0.06,
        "gross_pnl": 3.20
      }
    }
  ],
  "total": 47,
  "limit": 100,
  "offset": 0
}
```

| Position Field | Type | Description |
|---|---|---|
| `id` | int | Position ID |
| `strategy` | string | Strategy that opened this position |
| `asset` | string | `"BTC"`, `"ETH"`, `"SOL"`, etc. |
| `exchange` | string | Exchange name |
| `direction` | string | `"LONG"` or `"SHORT"` |
| `entryPrice` | float | Entry price (after slippage) |
| `entryTime` | string | ISO 8601 entry timestamp |
| `quantity` | float | Position size in asset units |
| `exitPrice` | float\|null | Exit price (after slippage), null if open |
| `exitTime` | string\|null | ISO 8601 exit timestamp |
| `exitReason` | string\|null | `"take_profit"`, `"stop_loss"`, `"timeout"`, or null |
| `realisedPnl` | float\|null | Net P&L after fees, null if open |
| `status` | string | `"OPEN"` or `"CLOSED"` |
| `metadata` | object\|null | Slippage, fees, and raw prices |

---

#### `GET /api/accounts/{account_id}/equity-curve`

Mark-to-market time series for an account.

**Query params:**

| Param | Type | Default | Description |
|---|---|---|---|
| `start_date` | datetime | none | Filter start (ISO 8601) |
| `end_date` | datetime | none | Filter end (ISO 8601) |

**Response:**

```json
{
  "data": [
    {
      "timestamp": "2025-06-15T10:00:00+00:00",
      "totalEquity": 10200.50,
      "unrealisedPnl": 50.00,
      "realisedPnl": 150.50,
      "openPositions": 1
    }
  ]
}
```

**Errors:**
- `404` — account not found

---

### Portfolios

#### `GET /api/portfolios`

List portfolios with their member accounts.

**Response:**

```json
{
  "portfolios": [
    {
      "id": 1,
      "name": "default",
      "description": "All accounts",
      "createdAt": "2025-06-01T00:00:00+00:00",
      "accounts": [
        { "id": 1, "name": "funding_rate_hyperliquid", "exchange": "hyperliquid", "strategy": "funding_rate" },
        { "id": 2, "name": "rsi_hyperliquid", "exchange": "hyperliquid", "strategy": "rsi_mean_reversion" }
      ]
    }
  ]
}
```

---

#### `POST /api/portfolios`

Create a new portfolio.

**Request body:**

```json
{
  "name": "aggressive",
  "description": "High-risk strategies"
}
```

| Field | Type | Required | Default |
|---|---|---|---|
| `name` | string | yes | — |
| `description` | string | no | null |

**Response (201):**

```json
{ "id": 2, "name": "aggressive" }
```

**Errors:**
- `409` — name already exists

---

#### `POST /api/portfolios/{portfolio_id}/accounts/{account_id}`

Add an account to a portfolio.

**Response (201):**

```json
{ "portfolioId": 1, "accountId": 3 }
```

**Errors:**
- `404` — portfolio or account not found
- `409` — account already in portfolio

---

#### `DELETE /api/portfolios/{portfolio_id}/accounts/{account_id}`

Remove an account from a portfolio.

**Response:**

```json
{ "ok": true }
```

**Errors:**
- `404` — membership not found

---

#### `GET /api/portfolios/{portfolio_id}/summary`

Aggregated metrics across all member accounts.

**Response:**

```json
{
  "id": 1,
  "name": "default",
  "totalEquity": 25300.50,
  "unrealisedPnl": 200.00,
  "realisedPnl": 800.50,
  "openPositions": 4,
  "totalTrades": 120,
  "winRate": 58.33,
  "totalPnl": 800.50,
  "profitFactor": 1.65,
  "sharpeRatio": 1.20,
  "sortinoRatio": 1.75,
  "maxDrawdown": 4.50,
  "expectancy": 8.25,
  "avgHoldMinutes": 38.00
}
```

**Errors:**
- `404` — portfolio not found

---

#### `GET /api/portfolios/{portfolio_id}/equity-curve`

Aggregated MTM time series for a portfolio (member account snapshots summed by timestamp).

**Query params:**

| Param | Type | Default | Description |
|---|---|---|---|
| `start_date` | datetime | none | Filter start (ISO 8601) |
| `end_date` | datetime | none | Filter end (ISO 8601) |

**Response:**

```json
{
  "data": [
    {
      "timestamp": "2025-06-15T10:00:00+00:00",
      "totalEquity": 25300.50,
      "unrealisedPnl": 200.00,
      "realisedPnl": 800.50,
      "openPositions": 4
    }
  ]
}
```

**Errors:**
- `404` — portfolio not found

---

### Strategies

#### `GET /api/strategies`

List all registered strategies with performance metrics. Includes strategies from both the code registry and historical positions in the DB.

**Response:**

```json
{
  "strategies": [
    {
      "name": "funding_rate",
      "enabled": true,
      "description": "Trades funding rate extremes on perpetual futures.",
      "docs": {
        "rationale": "...",
        "entry_logic": "...",
        "exit_logic": "...",
        "parameters": { "threshold": "0.01%" }
      },
      "assets": ["BTC", "ETH", "SOL"],
      "exchanges": ["hyperliquid"],
      "interval": "1m",
      "totalTrades": 47,
      "winRate": 63.83,
      "avgWin": 15.25,
      "avgLoss": -8.50,
      "totalPnl": 324.75,
      "profitFactor": 1.85,
      "sharpeRatio": 1.42,
      "sortinoRatio": 2.01,
      "maxDrawdown": 3.25,
      "expectancy": 12.50,
      "avgHoldMinutes": 42.30
    }
  ]
}
```

| Field | Type | Description |
|---|---|---|
| `name` | string | Strategy identifier |
| `enabled` | bool | Whether the strategy is enabled in config |
| `description` | string | Human-readable description from docstring |
| `docs` | object | Structured documentation (rationale, entry/exit logic, parameters) |
| `assets` | string[] | Assets this strategy trades |
| `exchanges` | string[] | Exchanges this strategy targets |
| `interval` | string | Candle interval used (e.g. `"1m"`) |
| `avgWin` | float | Average winning trade P&L |
| `avgLoss` | float | Average losing trade P&L (negative) |

Plus [Metrics Fields](#metrics-fields).

---

#### `GET /api/strategies/{strategy_name}/signals`

Paginated signal history for a strategy.

**Query params:**

| Param | Type | Default | Description |
|---|---|---|---|
| `limit` | int | 100 | Page size |
| `offset` | int | 0 | Pagination offset |
| `start_date` | datetime | none | Filter start (ISO 8601) |
| `end_date` | datetime | none | Filter end (ISO 8601) |

**Response:**

```json
{
  "signals": [
    {
      "id": 501,
      "timestamp": "2025-06-15T11:30:00+00:00",
      "asset": "BTC",
      "exchange": "hyperliquid",
      "direction": "LONG",
      "confidence": 0.82,
      "entryPrice": 60000.0,
      "metadata": { "funding_rate": "0.002" },
      "actedOn": true
    }
  ],
  "total": 250,
  "limit": 100,
  "offset": 0
}
```

| Signal Field | Type | Description |
|---|---|---|
| `id` | int | Signal ID |
| `timestamp` | string | ISO 8601 |
| `asset` | string | Asset symbol |
| `exchange` | string | Exchange name |
| `direction` | string | `"LONG"` or `"SHORT"` |
| `confidence` | float\|null | Signal confidence (0.0 to 1.0) |
| `entryPrice` | float\|null | Suggested entry price |
| `metadata` | object\|null | Strategy-specific data |
| `actedOn` | bool | Whether the paper engine opened a position for this signal |

---

#### `GET /api/strategies/{strategy_name}/trades`

Paginated trade history for a strategy (across all accounts).

**Query params:**

| Param | Type | Default | Description |
|---|---|---|---|
| `limit` | int | 100 | Page size |
| `offset` | int | 0 | Pagination offset |
| `status` | string | all | Filter: `"OPEN"` or `"CLOSED"` |

**Response:**

```json
{
  "trades": [
    {
      "id": 142,
      "accountId": 1,
      "asset": "BTC",
      "exchange": "hyperliquid",
      "direction": "LONG",
      "entryPrice": 60100.10,
      "entryTime": "2025-06-15T10:30:00+00:00",
      "quantity": 0.0033,
      "exitPrice": 61050.00,
      "exitTime": "2025-06-15T11:15:00+00:00",
      "exitReason": "take_profit",
      "realisedPnl": 3.14,
      "status": "CLOSED",
      "metadata": { "raw_price": 60000.0, "slippage_pct": 0.001 }
    }
  ],
  "total": 47,
  "limit": 100,
  "offset": 0
}
```

Note: trades include `accountId` to identify which account executed the trade.

---

#### `GET /api/strategies/{strategy_name}/docs`

Structured documentation for a strategy.

**Response:**

```json
{
  "name": "funding_rate",
  "description": "Trades funding rate extremes on perpetual futures.",
  "docs": {
    "rationale": "When funding rates are extremely positive, shorts are overpaying...",
    "entry_logic": "Enter SHORT when 8h funding rate > threshold...",
    "exit_logic": "Take profit at 2x risk, stop loss at 1x risk...",
    "parameters": {
      "funding_threshold": "0.01%",
      "lookback_hours": 8
    }
  },
  "assets": ["BTC", "ETH", "SOL"],
  "exchanges": ["hyperliquid"],
  "interval": "1m"
}
```

**Errors:**
- `404` — strategy not found in registry

---

### Global / Legacy Endpoints

These aggregate across all active accounts for backward compatibility with existing dashboard views.

#### `GET /api/summary`

Portfolio-level summary aggregated across all active accounts.

**Response:**

```json
{
  "totalEquity": 25300.50,
  "unrealisedPnl": 200.00,
  "realisedPnl": 800.50,
  "openPositions": 4,
  "dailyPnl": 45.25,
  "sharpeRatio": 1.20,
  "sortinoRatio": 1.75,
  "maxDrawdown": 4.50,
  "expectancy": 8.25,
  "avgHoldMinutes": 38.00,
  "profitFactor": 1.65,
  "lastUpdate": "2025-06-15T12:00:00+00:00"
}
```

| Field | Type | Description |
|---|---|---|
| `totalEquity` | float | Sum of all active account equities |
| `unrealisedPnl` | float | Aggregate unrealised P&L |
| `realisedPnl` | float | Aggregate realised P&L |
| `openPositions` | int | Total open positions across all accounts |
| `dailyPnl` | float | Today's equity change (UTC midnight to latest) |
| `lastUpdate` | string\|null | Most recent MTM timestamp |

Plus [Metrics Fields](#metrics-fields).

---

#### `GET /api/equity-curve`

Aggregated equity curve across all accounts.

**Query params:**

| Param | Type | Default | Description |
|---|---|---|---|
| `start_date` | datetime | none | Filter start (ISO 8601) |
| `end_date` | datetime | none | Filter end (ISO 8601) |

**Response:** same shape as portfolio equity-curve.

---

#### `GET /api/positions/open`

All currently open positions across all accounts, with live unrealised P&L.

**Response:**

```json
{
  "positions": [
    {
      "id": 150,
      "accountId": 1,
      "strategy": "funding_rate",
      "asset": "BTC",
      "exchange": "hyperliquid",
      "direction": "LONG",
      "entryPrice": 60100.10,
      "entryTime": "2025-06-15T11:30:00+00:00",
      "quantity": 0.0033,
      "currentPrice": 60500.00,
      "unrealisedPnl": 1.32,
      "metadata": { "raw_price": 60000.0, "slippage_pct": 0.001 }
    }
  ]
}
```

| Field | Type | Description |
|---|---|---|
| `currentPrice` | float\|null | Latest candle close for this asset (null if no data) |
| `unrealisedPnl` | float | Live unrealised P&L based on current price |

---

#### `GET /api/assets/{asset}/performance`

Per-asset P&L breakdown by strategy.

**Response:**

```json
{
  "asset": "BTC",
  "totalTrades": 85,
  "totalPnl": 425.30,
  "byStrategy": {
    "funding_rate": {
      "trades": 47,
      "winRate": 63.83,
      "totalPnl": 324.75,
      "avgHoldMinutes": 42.30
    },
    "rsi_mean_reversion": {
      "trades": 38,
      "winRate": 52.63,
      "totalPnl": 100.55,
      "avgHoldMinutes": 55.10
    }
  }
}
```

---

## Metrics Fields

These fields appear in summary and strategy responses:

| Field | Type | Description |
|---|---|---|
| `totalTrades` | int | Total closed positions |
| `winRate` | float | Percentage of profitable trades (0-100) |
| `totalPnl` | float | Cumulative net P&L |
| `profitFactor` | float | Gross profit / gross loss (0 if no losses) |
| `sharpeRatio` | float | Annualised risk-adjusted return (sample std, sqrt(252)) |
| `sortinoRatio` | float | Like Sharpe but only penalises downside volatility |
| `maxDrawdown` | float | Maximum peak-to-trough equity decline (percentage, 0-100) |
| `expectancy` | float | Expected P&L per trade (winRate * avgWin + lossRate * avgLoss) |
| `avgHoldMinutes` | float | Average position duration in minutes |

---

## Pagination

Paginated endpoints return:

```json
{
  "total": 250,
  "limit": 100,
  "offset": 0
}
```

Use `limit` and `offset` query params to paginate. Default page size is 100.

---

## Error Responses

All errors follow:

```json
{ "detail": "Human-readable error message" }
```

| Status | Meaning |
|---|---|
| `404` | Resource not found |
| `409` | Conflict (duplicate name, already exists) |
| `422` | Validation error (bad request body) |
