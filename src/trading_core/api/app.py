"""FastAPI application for trading dashboard backend."""

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import select, func, and_, distinct
from sqlalchemy.orm import Session
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional, Generator
import structlog

from trading_core.db.engine import get_session as _get_session, init_engine
from trading_core.db.tables.signals import SignalRow
from trading_core.db.tables.paper import PositionRow, MarkToMarketRow, PortfolioRow
from trading_core.db.tables.accounts import (
    AccountMarkToMarketRow,
    AccountPositionRow,
    AccountRow,
    PortfolioGroupRow,
    PortfolioMemberRow,
)
from trading_core.db.tables.market_data import CandleRow
from trading_core.config.loader import load_config
from trading_core.metrics import (
    MetricsCache,
    compute_account_metrics,
    compute_portfolio_group_metrics,
    compute_strategy_metrics,
    compute_portfolio_metrics,
)
import trading_core.strategy.strategies  # noqa: F401 — trigger @register decorators
from trading_core.strategy import STRATEGY_REGISTRY

logger = structlog.get_logger()

app = FastAPI(
    title="Trading Dashboard API",
    description="Backend API for trading strategy analysis and visualization",
    version="0.1.0"
)

# CORS middleware - adjust origins in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure properly for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load config once at startup
config = load_config()

# Metrics cache (60s TTL)
_metrics_cache = MetricsCache(ttl_seconds=60.0)


def get_db() -> Generator[Session, None, None]:
    """Dependency to get DB session."""
    gen = _get_session()
    session = next(gen)
    try:
        yield session
    finally:
        try:
            next(gen)
        except StopIteration:
            pass


@app.on_event("startup")
async def startup_event():
    """Initialize database engine on startup."""
    # Initialize the database engine
    init_engine(config.database.url)
    logger.info("Database engine initialized")


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()}


# ═══════════════════════════════════════════════════════════════
# Account CRUD
# ═══════════════════════════════════════════════════════════════


class CreateAccountRequest(BaseModel):
    name: str
    exchange: str
    strategy: str
    initial_capital: float = 10000


class PatchAccountRequest(BaseModel):
    name: Optional[str] = None
    active: Optional[bool] = None


@app.get("/api/accounts")
async def list_accounts(session: Session = Depends(get_db)):
    """List all accounts with current equity snapshot."""
    accounts = session.execute(
        select(AccountRow).order_by(AccountRow.id)
    ).scalars().all()

    result = []
    for acct in accounts:
        # Latest MTM for quick equity
        latest_mtm = session.execute(
            select(AccountMarkToMarketRow)
            .where(AccountMarkToMarketRow.account_id == acct.id)
            .order_by(AccountMarkToMarketRow.ts.desc())
            .limit(1)
        ).scalar_one_or_none()

        result.append({
            "id": acct.id,
            "name": acct.name,
            "exchange": acct.exchange,
            "strategy": acct.strategy,
            "initialCapital": float(acct.initial_capital),
            "active": acct.active,
            "createdAt": acct.created_at.isoformat() if acct.created_at else None,
            "currentEquity": float(latest_mtm.total_equity) if latest_mtm else float(acct.initial_capital),
            "unrealisedPnl": float(latest_mtm.unrealised_pnl) if latest_mtm else 0,
            "realisedPnl": float(latest_mtm.realised_pnl) if latest_mtm else 0,
            "openPositions": latest_mtm.open_positions if latest_mtm else 0,
        })

    return {"accounts": result}


@app.post("/api/accounts", status_code=201)
async def create_account(req: CreateAccountRequest, session: Session = Depends(get_db)):
    """Create a new account."""
    existing = session.execute(
        select(AccountRow).where(AccountRow.name == req.name)
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail=f"Account name {req.name!r} already exists")

    row = AccountRow(
        name=req.name,
        exchange=req.exchange,
        strategy=req.strategy,
        initial_capital=req.initial_capital,
        active=True,
        created_at=datetime.now(timezone.utc),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return {"id": row.id, "name": row.name}


@app.patch("/api/accounts/{account_id}")
async def patch_account(account_id: int, req: PatchAccountRequest, session: Session = Depends(get_db)):
    """Toggle active status or rename an account."""
    acct = session.get(AccountRow, account_id)
    if not acct:
        raise HTTPException(status_code=404, detail="Account not found")

    if req.name is not None:
        # Check uniqueness
        conflict = session.execute(
            select(AccountRow).where(AccountRow.name == req.name, AccountRow.id != account_id)
        ).scalar_one_or_none()
        if conflict:
            raise HTTPException(status_code=409, detail=f"Account name {req.name!r} already exists")
        acct.name = req.name

    if req.active is not None:
        acct.active = req.active

    session.commit()
    return {"id": acct.id, "name": acct.name, "active": acct.active}


@app.get("/api/accounts/{account_id}/summary")
async def get_account_summary(account_id: int, session: Session = Depends(get_db)):
    """Get account-level metrics and equity."""
    acct = session.get(AccountRow, account_id)
    if not acct:
        raise HTTPException(status_code=404, detail="Account not found")

    cache_key = f"account:{account_id}"
    m = _metrics_cache.get(cache_key)
    if m is None:
        m = compute_account_metrics(session, account_id)
        _metrics_cache.set(cache_key, m)

    latest_mtm = session.execute(
        select(AccountMarkToMarketRow)
        .where(AccountMarkToMarketRow.account_id == account_id)
        .order_by(AccountMarkToMarketRow.ts.desc())
        .limit(1)
    ).scalar_one_or_none()

    return {
        "id": acct.id,
        "name": acct.name,
        "exchange": acct.exchange,
        "strategy": acct.strategy,
        "initialCapital": float(acct.initial_capital),
        "currentEquity": float(latest_mtm.total_equity) if latest_mtm else float(acct.initial_capital),
        "unrealisedPnl": float(latest_mtm.unrealised_pnl) if latest_mtm else 0,
        "realisedPnl": float(latest_mtm.realised_pnl) if latest_mtm else 0,
        "openPositions": latest_mtm.open_positions if latest_mtm else 0,
        "totalTrades": m.total_trades,
        "winRate": round(m.win_rate, 2),
        "totalPnl": round(m.total_pnl, 4),
        "profitFactor": round(m.profit_factor, 2),
        "sharpeRatio": round(m.sharpe_ratio, 2),
        "sortinoRatio": round(m.sortino_ratio, 2),
        "maxDrawdown": round(m.max_drawdown, 2),
        "expectancy": round(m.expectancy, 2),
        "avgHoldMinutes": round(m.avg_hold_minutes, 2),
    }


@app.get("/api/accounts/{account_id}/positions")
async def get_account_positions(
    account_id: int,
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    session: Session = Depends(get_db),
):
    """Get positions for a specific account."""
    acct = session.get(AccountRow, account_id)
    if not acct:
        raise HTTPException(status_code=404, detail="Account not found")

    query = select(AccountPositionRow).where(AccountPositionRow.account_id == account_id)
    if status:
        query = query.where(AccountPositionRow.status == status)

    total_count = session.execute(
        select(func.count(AccountPositionRow.id))
        .where(AccountPositionRow.account_id == account_id)
    ).scalar()

    positions = session.execute(
        query.order_by(AccountPositionRow.entry_ts.desc()).limit(limit).offset(offset)
    ).scalars().all()

    return {
        "positions": [
            {
                "id": p.id,
                "strategy": p.strategy,
                "asset": p.asset,
                "exchange": p.exchange,
                "direction": p.direction,
                "entryPrice": float(p.entry_price),
                "entryTime": p.entry_ts.isoformat(),
                "quantity": float(p.quantity),
                "exitPrice": float(p.exit_price) if p.exit_price else None,
                "exitTime": p.exit_ts.isoformat() if p.exit_ts else None,
                "exitReason": p.exit_reason,
                "realisedPnl": float(p.realised_pnl) if p.realised_pnl else None,
                "status": p.status,
                "metadata": p.metadata_,
            }
            for p in positions
        ],
        "total": total_count,
        "limit": limit,
        "offset": offset,
    }


@app.get("/api/accounts/{account_id}/equity-curve")
async def get_account_equity_curve(
    account_id: int,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    session: Session = Depends(get_db),
):
    """Get MTM series for a specific account."""
    acct = session.get(AccountRow, account_id)
    if not acct:
        raise HTTPException(status_code=404, detail="Account not found")

    query = select(AccountMarkToMarketRow).where(
        AccountMarkToMarketRow.account_id == account_id
    )
    if start_date:
        query = query.where(AccountMarkToMarketRow.ts >= start_date)
    if end_date:
        query = query.where(AccountMarkToMarketRow.ts <= end_date)

    snapshots = session.execute(
        query.order_by(AccountMarkToMarketRow.ts)
    ).scalars().all()

    return {
        "data": [
            {
                "timestamp": s.ts.isoformat(),
                "totalEquity": float(s.total_equity),
                "unrealisedPnl": float(s.unrealised_pnl),
                "realisedPnl": float(s.realised_pnl),
                "openPositions": s.open_positions,
            }
            for s in snapshots
        ]
    }


# ═══════════════════════════════════════════════════════════════
# Portfolio CRUD
# ═══════════════════════════════════════════════════════════════


class CreatePortfolioRequest(BaseModel):
    name: str
    description: Optional[str] = None


@app.get("/api/portfolios")
async def list_portfolios(session: Session = Depends(get_db)):
    """List portfolios with member accounts."""
    portfolios = session.execute(
        select(PortfolioGroupRow).order_by(PortfolioGroupRow.id)
    ).scalars().all()

    result = []
    for pf in portfolios:
        members = session.execute(
            select(PortfolioMemberRow).where(PortfolioMemberRow.portfolio_id == pf.id)
        ).scalars().all()

        account_ids = [m.account_id for m in members]
        accounts = []
        if account_ids:
            accounts = session.execute(
                select(AccountRow).where(AccountRow.id.in_(account_ids))
            ).scalars().all()

        result.append({
            "id": pf.id,
            "name": pf.name,
            "description": pf.description,
            "createdAt": pf.created_at.isoformat() if pf.created_at else None,
            "accounts": [
                {"id": a.id, "name": a.name, "exchange": a.exchange, "strategy": a.strategy}
                for a in accounts
            ],
        })

    return {"portfolios": result}


@app.post("/api/portfolios", status_code=201)
async def create_portfolio(req: CreatePortfolioRequest, session: Session = Depends(get_db)):
    """Create a new portfolio."""
    existing = session.execute(
        select(PortfolioGroupRow).where(PortfolioGroupRow.name == req.name)
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail=f"Portfolio name {req.name!r} already exists")

    row = PortfolioGroupRow(
        name=req.name,
        description=req.description,
        created_at=datetime.now(timezone.utc),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return {"id": row.id, "name": row.name}


@app.post("/api/portfolios/{portfolio_id}/accounts/{account_id}", status_code=201)
async def add_account_to_portfolio(
    portfolio_id: int,
    account_id: int,
    session: Session = Depends(get_db),
):
    """Add an account to a portfolio."""
    pf = session.get(PortfolioGroupRow, portfolio_id)
    if not pf:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    acct = session.get(AccountRow, account_id)
    if not acct:
        raise HTTPException(status_code=404, detail="Account not found")

    existing = session.execute(
        select(PortfolioMemberRow).where(
            PortfolioMemberRow.portfolio_id == portfolio_id,
            PortfolioMemberRow.account_id == account_id,
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Account already in portfolio")

    member = PortfolioMemberRow(portfolio_id=portfolio_id, account_id=account_id)
    session.add(member)
    session.commit()
    return {"portfolioId": portfolio_id, "accountId": account_id}


@app.delete("/api/portfolios/{portfolio_id}/accounts/{account_id}")
async def remove_account_from_portfolio(
    portfolio_id: int,
    account_id: int,
    session: Session = Depends(get_db),
):
    """Remove an account from a portfolio."""
    member = session.execute(
        select(PortfolioMemberRow).where(
            PortfolioMemberRow.portfolio_id == portfolio_id,
            PortfolioMemberRow.account_id == account_id,
        )
    ).scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="Membership not found")

    session.delete(member)
    session.commit()
    return {"ok": True}


@app.get("/api/portfolios/{portfolio_id}/summary")
async def get_portfolio_group_summary(portfolio_id: int, session: Session = Depends(get_db)):
    """Aggregated metrics for a portfolio group."""
    pf = session.get(PortfolioGroupRow, portfolio_id)
    if not pf:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    cache_key = f"portfolio_group:{portfolio_id}"
    m = _metrics_cache.get(cache_key)
    if m is None:
        m = compute_portfolio_group_metrics(session, portfolio_id)
        _metrics_cache.set(cache_key, m)

    # Aggregate equity from member accounts
    members = session.execute(
        select(PortfolioMemberRow.account_id).where(PortfolioMemberRow.portfolio_id == portfolio_id)
    ).scalars().all()

    total_equity = 0.0
    total_unrealised = 0.0
    total_realised = 0.0
    total_open = 0
    for aid in members:
        latest_mtm = session.execute(
            select(AccountMarkToMarketRow)
            .where(AccountMarkToMarketRow.account_id == aid)
            .order_by(AccountMarkToMarketRow.ts.desc())
            .limit(1)
        ).scalar_one_or_none()
        if latest_mtm:
            total_equity += float(latest_mtm.total_equity)
            total_unrealised += float(latest_mtm.unrealised_pnl)
            total_realised += float(latest_mtm.realised_pnl)
            total_open += latest_mtm.open_positions
        else:
            acct = session.get(AccountRow, aid)
            total_equity += float(acct.initial_capital) if acct else 0

    return {
        "id": pf.id,
        "name": pf.name,
        "totalEquity": round(total_equity, 4),
        "unrealisedPnl": round(total_unrealised, 4),
        "realisedPnl": round(total_realised, 4),
        "openPositions": total_open,
        "totalTrades": m.total_trades,
        "winRate": round(m.win_rate, 2),
        "totalPnl": round(m.total_pnl, 4),
        "profitFactor": round(m.profit_factor, 2),
        "sharpeRatio": round(m.sharpe_ratio, 2),
        "sortinoRatio": round(m.sortino_ratio, 2),
        "maxDrawdown": round(m.max_drawdown, 2),
        "expectancy": round(m.expectancy, 2),
        "avgHoldMinutes": round(m.avg_hold_minutes, 2),
    }


@app.get("/api/portfolios/{portfolio_id}/equity-curve")
async def get_portfolio_group_equity_curve(
    portfolio_id: int,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    session: Session = Depends(get_db),
):
    """Aggregated MTM for a portfolio group."""
    pf = session.get(PortfolioGroupRow, portfolio_id)
    if not pf:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    members = session.execute(
        select(PortfolioMemberRow.account_id).where(PortfolioMemberRow.portfolio_id == portfolio_id)
    ).scalars().all()

    if not members:
        return {"data": []}

    query = select(AccountMarkToMarketRow).where(
        AccountMarkToMarketRow.account_id.in_(members)
    )
    if start_date:
        query = query.where(AccountMarkToMarketRow.ts >= start_date)
    if end_date:
        query = query.where(AccountMarkToMarketRow.ts <= end_date)

    snapshots = session.execute(
        query.order_by(AccountMarkToMarketRow.ts)
    ).scalars().all()

    # Aggregate by timestamp
    by_ts: dict[str, dict] = {}
    for s in snapshots:
        ts_key = s.ts.isoformat()
        if ts_key not in by_ts:
            by_ts[ts_key] = {
                "timestamp": ts_key,
                "totalEquity": 0.0,
                "unrealisedPnl": 0.0,
                "realisedPnl": 0.0,
                "openPositions": 0,
            }
        by_ts[ts_key]["totalEquity"] += float(s.total_equity)
        by_ts[ts_key]["unrealisedPnl"] += float(s.unrealised_pnl)
        by_ts[ts_key]["realisedPnl"] += float(s.realised_pnl)
        by_ts[ts_key]["openPositions"] += s.open_positions

    return {"data": list(by_ts.values())}


# ═══════════════════════════════════════════════════════════════
# Strategy endpoints (updated to query new schema)
# ═══════════════════════════════════════════════════════════════


@app.get("/api/strategies")
async def list_strategies(session: Session = Depends(get_db)):
    """List all registered strategies with current performance metrics."""
    strategies = []

    # Union registry names with DB names to catch legacy strategies
    db_names = set(session.execute(
        select(distinct(AccountPositionRow.strategy))
    ).scalars().all())
    strategy_names = sorted(set(STRATEGY_REGISTRY) | db_names)

    for strategy_name in strategy_names:
        cache_key = f"strategy:{strategy_name}"
        cached = _metrics_cache.get(cache_key)
        if cached is not None:
            strategies.append(cached)
            continue

        m = compute_strategy_metrics(session, strategy_name)

        strategy_config = config.strategies.get(strategy_name, {})
        enabled = strategy_config.get("enabled", False)

        cls = STRATEGY_REGISTRY.get(strategy_name)

        entry = {
            "name": strategy_name,
            "enabled": enabled,
            "description": (cls.__doc__ or "").strip() if cls else "",
            "docs": cls.docs if cls else {},
            "assets": cls.assets if cls else [],
            "exchanges": cls.exchanges if cls else [],
            "interval": cls.interval if cls else "",
            "totalTrades": m.total_trades,
            "winRate": round(m.win_rate, 2),
            "avgWin": round(m.avg_win, 4),
            "avgLoss": round(m.avg_loss, 4),
            "totalPnl": round(m.total_pnl, 4),
            "profitFactor": round(m.profit_factor, 2),
            "sharpeRatio": round(m.sharpe_ratio, 2),
            "sortinoRatio": round(m.sortino_ratio, 2),
            "maxDrawdown": round(m.max_drawdown, 2),
            "expectancy": round(m.expectancy, 2),
            "avgHoldMinutes": round(m.avg_hold_minutes, 2),
        }
        _metrics_cache.set(cache_key, entry)
        strategies.append(entry)

    return {"strategies": strategies}


@app.get("/api/strategies/{strategy_name}/signals")
async def get_strategy_signals(
    strategy_name: str,
    limit: int = 100,
    offset: int = 0,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    session: Session = Depends(get_db)
):
    """Get paginated signal history for a specific strategy."""
    query = select(SignalRow).where(SignalRow.strategy == strategy_name)

    if start_date:
        query = query.where(SignalRow.ts >= start_date)
    if end_date:
        query = query.where(SignalRow.ts <= end_date)

    # Get total count
    total_count = session.execute(
        select(func.count(SignalRow.id))
        .where(SignalRow.strategy == strategy_name)
    ).scalar()

    # Get paginated results
    signals = session.execute(
        query.order_by(SignalRow.ts.desc())
        .limit(limit)
        .offset(offset)
    ).scalars().all()

    return {
        "signals": [
            {
                "id": s.id,
                "timestamp": s.ts.isoformat(),
                "asset": s.asset,
                "exchange": s.exchange,
                "direction": s.direction,
                "confidence": float(s.confidence) if s.confidence else None,
                "entryPrice": float(s.entry_price) if s.entry_price else None,
                "metadata": s.metadata_,
                "actedOn": s.acted_on
            }
            for s in signals
        ],
        "total": total_count,
        "limit": limit,
        "offset": offset
    }


@app.get("/api/strategies/{strategy_name}/trades")
async def get_strategy_trades(
    strategy_name: str,
    limit: int = 100,
    offset: int = 0,
    status: Optional[str] = None,
    session: Session = Depends(get_db)
):
    """Get paginated trade history for a specific strategy."""
    query = select(AccountPositionRow).where(AccountPositionRow.strategy == strategy_name)

    if status:
        query = query.where(AccountPositionRow.status == status)

    total_count = session.execute(
        select(func.count(AccountPositionRow.id))
        .where(AccountPositionRow.strategy == strategy_name)
    ).scalar()

    positions = session.execute(
        query.order_by(AccountPositionRow.entry_ts.desc())
        .limit(limit)
        .offset(offset)
    ).scalars().all()

    return {
        "trades": [
            {
                "id": p.id,
                "accountId": p.account_id,
                "asset": p.asset,
                "exchange": p.exchange,
                "direction": p.direction,
                "entryPrice": float(p.entry_price),
                "entryTime": p.entry_ts.isoformat(),
                "quantity": float(p.quantity),
                "exitPrice": float(p.exit_price) if p.exit_price else None,
                "exitTime": p.exit_ts.isoformat() if p.exit_ts else None,
                "exitReason": p.exit_reason,
                "realisedPnl": float(p.realised_pnl) if p.realised_pnl else None,
                "status": p.status,
                "metadata": p.metadata_
            }
            for p in positions
        ],
        "total": total_count,
        "limit": limit,
        "offset": offset
    }


@app.get("/api/strategies/{strategy_name}/docs")
async def get_strategy_docs(strategy_name: str):
    """Get structured documentation for a strategy."""
    if strategy_name not in STRATEGY_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Strategy {strategy_name!r} not found")

    cls = STRATEGY_REGISTRY[strategy_name]
    return {
        "name": cls.name,
        "description": (cls.__doc__ or "").strip(),
        "docs": cls.docs,
        "assets": cls.assets,
        "exchanges": cls.exchanges,
        "interval": cls.interval,
    }


# ═══════════════════════════════════════════════════════════════
# Legacy-compatible endpoints (query new schema, backward-compat response)
# ═══════════════════════════════════════════════════════════════


@app.get("/api/equity-curve")
async def get_equity_curve(
    strategy: Optional[str] = None,
    asset: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    interval: str = "1h",
    session: Session = Depends(get_db)
):
    """Get time-series equity data for charting.

    Aggregates across all accounts for backward compatibility.
    """
    # Try new schema first — aggregate all account MTM
    all_accounts = session.execute(select(AccountRow.id)).scalars().all()
    if all_accounts:
        query = select(AccountMarkToMarketRow).where(
            AccountMarkToMarketRow.account_id.in_(all_accounts)
        )
        if start_date:
            query = query.where(AccountMarkToMarketRow.ts >= start_date)
        if end_date:
            query = query.where(AccountMarkToMarketRow.ts <= end_date)

        snapshots = session.execute(
            query.order_by(AccountMarkToMarketRow.ts)
        ).scalars().all()

        # Aggregate by timestamp
        by_ts: dict[str, dict] = {}
        for s in snapshots:
            ts_key = s.ts.isoformat()
            if ts_key not in by_ts:
                by_ts[ts_key] = {
                    "timestamp": ts_key,
                    "totalEquity": 0.0,
                    "unrealisedPnl": 0.0,
                    "realisedPnl": 0.0,
                    "openPositions": 0,
                }
            by_ts[ts_key]["totalEquity"] += float(s.total_equity)
            by_ts[ts_key]["unrealisedPnl"] += float(s.unrealised_pnl)
            by_ts[ts_key]["realisedPnl"] += float(s.realised_pnl)
            by_ts[ts_key]["openPositions"] += s.open_positions

        return {"data": list(by_ts.values())}

    # Fall back to old schema
    portfolio = session.execute(
        select(PortfolioRow).where(PortfolioRow.name == "default")
    ).scalar_one_or_none()

    if not portfolio:
        return {"data": []}

    query = select(MarkToMarketRow).where(
        MarkToMarketRow.portfolio_id == portfolio.id
    )
    if start_date:
        query = query.where(MarkToMarketRow.ts >= start_date)
    if end_date:
        query = query.where(MarkToMarketRow.ts <= end_date)

    snapshots = session.execute(
        query.order_by(MarkToMarketRow.ts)
    ).scalars().all()

    return {
        "data": [
            {
                "timestamp": s.ts.isoformat(),
                "totalEquity": float(s.total_equity),
                "unrealisedPnl": float(s.unrealised_pnl),
                "realisedPnl": float(s.realised_pnl),
                "openPositions": s.open_positions,
            }
            for s in snapshots
        ]
    }


@app.get("/api/positions/open")
async def get_open_positions(session: Session = Depends(get_db)):
    """Get currently open positions with unrealized P&L."""
    positions = session.execute(
        select(AccountPositionRow)
        .where(AccountPositionRow.status == "OPEN")
        .order_by(AccountPositionRow.entry_ts.desc())
    ).scalars().all()

    # Get current prices for each asset
    current_prices = {}
    for position in positions:
        if position.asset not in current_prices:
            latest_candle = session.execute(
                select(CandleRow)
                .where(
                    and_(
                        CandleRow.asset == position.asset,
                        CandleRow.exchange == position.exchange,
                        CandleRow.interval == "1m"
                    )
                )
                .order_by(CandleRow.open_time.desc())
                .limit(1)
            ).scalar_one_or_none()

            if latest_candle:
                current_prices[position.asset] = latest_candle.close

    open_positions = []
    for position in positions:
        current_price = current_prices.get(position.asset)

        if current_price:
            if position.direction == "LONG":
                unrealised_pnl = (current_price - position.entry_price) * position.quantity
            else:
                unrealised_pnl = (position.entry_price - current_price) * position.quantity
        else:
            unrealised_pnl = Decimal("0")

        open_positions.append({
            "id": position.id,
            "accountId": position.account_id,
            "strategy": position.strategy,
            "asset": position.asset,
            "exchange": position.exchange,
            "direction": position.direction,
            "entryPrice": float(position.entry_price),
            "entryTime": position.entry_ts.isoformat(),
            "quantity": float(position.quantity),
            "currentPrice": float(current_price) if current_price else None,
            "unrealisedPnl": float(unrealised_pnl),
            "metadata": position.metadata_
        })

    return {"positions": open_positions}


@app.get("/api/assets/{asset}/performance")
async def get_asset_performance(asset: str, session: Session = Depends(get_db)):
    """Get per-asset P&L across all strategies."""
    positions = session.execute(
        select(AccountPositionRow)
        .where(
            and_(
                AccountPositionRow.asset == asset,
                AccountPositionRow.status == "CLOSED"
            )
        )
    ).scalars().all()

    by_strategy = {}
    for position in positions:
        if position.strategy not in by_strategy:
            by_strategy[position.strategy] = {
                "trades": 0,
                "wins": 0,
                "totalPnl": Decimal("0"),
                "avgHoldTime": timedelta()
            }

        strategy_data = by_strategy[position.strategy]
        strategy_data["trades"] += 1

        if position.realised_pnl > 0:
            strategy_data["wins"] += 1

        strategy_data["totalPnl"] += position.realised_pnl

        if position.exit_ts:
            hold_time = position.exit_ts - position.entry_ts
            strategy_data["avgHoldTime"] += hold_time

    performance = {
        "asset": asset,
        "totalTrades": len(positions),
        "totalPnl": float(sum(p.realised_pnl for p in positions)),
        "byStrategy": {}
    }

    for strategy_name, data in by_strategy.items():
        avg_hold_minutes = (
            data["avgHoldTime"].total_seconds() / 60 / data["trades"]
            if data["trades"] > 0 else 0
        )

        performance["byStrategy"][strategy_name] = {
            "trades": data["trades"],
            "winRate": round(data["wins"] / data["trades"] * 100, 2) if data["trades"] > 0 else 0,
            "totalPnl": float(data["totalPnl"]),
            "avgHoldMinutes": round(avg_hold_minutes, 2)
        }

    return performance


@app.get("/api/summary")
async def get_portfolio_summary(session: Session = Depends(get_db)):
    """Get portfolio-level metrics (backward-compat: aggregates all accounts)."""
    # Try new schema first
    all_accounts = session.execute(
        select(AccountRow).where(AccountRow.active == True)  # noqa: E712
    ).scalars().all()

    if all_accounts:
        # Find or create a default portfolio group for aggregation
        default_pf = session.execute(
            select(PortfolioGroupRow).where(PortfolioGroupRow.name == "default")
        ).scalar_one_or_none()

        total_equity = 0.0
        total_unrealised = 0.0
        total_realised = 0.0
        total_open = 0
        latest_ts = None

        for acct in all_accounts:
            latest_mtm = session.execute(
                select(AccountMarkToMarketRow)
                .where(AccountMarkToMarketRow.account_id == acct.id)
                .order_by(AccountMarkToMarketRow.ts.desc())
                .limit(1)
            ).scalar_one_or_none()
            if latest_mtm:
                total_equity += float(latest_mtm.total_equity)
                total_unrealised += float(latest_mtm.unrealised_pnl)
                total_realised += float(latest_mtm.realised_pnl)
                total_open += latest_mtm.open_positions
                if latest_ts is None or latest_mtm.ts > latest_ts:
                    latest_ts = latest_mtm.ts
            else:
                total_equity += float(acct.initial_capital)

        # Compute metrics from portfolio group if available, else from all positions
        if default_pf:
            cache_key = f"portfolio_group:{default_pf.id}"
            m = _metrics_cache.get(cache_key)
            if m is None:
                m = compute_portfolio_group_metrics(session, default_pf.id)
                _metrics_cache.set(cache_key, m)
        else:
            # No portfolio group — use a dummy StrategyMetrics
            from trading_core.metrics.formulas import StrategyMetrics
            m = StrategyMetrics()

        # Daily P&L
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        daily_pnl = 0.0
        for acct in all_accounts:
            today_first = session.execute(
                select(AccountMarkToMarketRow)
                .where(
                    and_(
                        AccountMarkToMarketRow.account_id == acct.id,
                        AccountMarkToMarketRow.ts >= today_start,
                    )
                )
                .order_by(AccountMarkToMarketRow.ts)
                .limit(1)
            ).scalar_one_or_none()
            today_last = session.execute(
                select(AccountMarkToMarketRow)
                .where(
                    and_(
                        AccountMarkToMarketRow.account_id == acct.id,
                        AccountMarkToMarketRow.ts >= today_start,
                    )
                )
                .order_by(AccountMarkToMarketRow.ts.desc())
                .limit(1)
            ).scalar_one_or_none()
            if today_first and today_last:
                daily_pnl += float(today_last.total_equity - today_first.total_equity)

        return {
            "totalEquity": round(total_equity, 4),
            "unrealisedPnl": round(total_unrealised, 4),
            "realisedPnl": round(total_realised, 4),
            "openPositions": total_open,
            "dailyPnl": round(daily_pnl, 4),
            "sharpeRatio": round(m.sharpe_ratio, 2),
            "sortinoRatio": round(m.sortino_ratio, 2),
            "maxDrawdown": round(m.max_drawdown, 2),
            "expectancy": round(m.expectancy, 2),
            "avgHoldMinutes": round(m.avg_hold_minutes, 2),
            "profitFactor": round(m.profit_factor, 2),
            "lastUpdate": latest_ts.isoformat() if latest_ts else None,
        }

    # Fall back to old schema
    portfolio = session.execute(
        select(PortfolioRow).where(PortfolioRow.name == "default")
    ).scalar_one_or_none()

    if not portfolio:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    latest_mtm = session.execute(
        select(MarkToMarketRow)
        .where(MarkToMarketRow.portfolio_id == portfolio.id)
        .order_by(MarkToMarketRow.ts.desc())
        .limit(1)
    ).scalar_one_or_none()

    if not latest_mtm:
        return {
            "totalEquity": float(portfolio.initial_capital),
            "unrealisedPnl": 0,
            "realisedPnl": 0,
            "openPositions": 0,
            "dailyReturn": 0,
            "sharpeRatio": 0,
            "sortinoRatio": 0,
            "maxDrawdown": 0,
            "expectancy": 0,
            "avgHoldMinutes": 0,
            "profitFactor": 0,
        }

    cache_key = f"portfolio:{portfolio.id}"
    cached_metrics = _metrics_cache.get(cache_key)
    if cached_metrics is None:
        cached_metrics = compute_portfolio_metrics(session, portfolio.id)
        _metrics_cache.set(cache_key, cached_metrics)

    m = cached_metrics

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_start_mtm = session.execute(
        select(MarkToMarketRow)
        .where(
            and_(
                MarkToMarketRow.portfolio_id == portfolio.id,
                MarkToMarketRow.ts >= today_start
            )
        )
        .order_by(MarkToMarketRow.ts)
        .limit(1)
    ).scalar_one_or_none()

    daily_pnl = 0
    if today_start_mtm:
        daily_pnl = float(latest_mtm.total_equity - today_start_mtm.total_equity)

    return {
        "totalEquity": float(latest_mtm.total_equity),
        "unrealisedPnl": float(latest_mtm.unrealised_pnl),
        "realisedPnl": float(latest_mtm.realised_pnl),
        "openPositions": latest_mtm.open_positions,
        "dailyPnl": daily_pnl,
        "sharpeRatio": round(m.sharpe_ratio, 2),
        "sortinoRatio": round(m.sortino_ratio, 2),
        "maxDrawdown": round(m.max_drawdown, 2),
        "expectancy": round(m.expectancy, 2),
        "avgHoldMinutes": round(m.avg_hold_minutes, 2),
        "profitFactor": round(m.profit_factor, 2),
        "lastUpdate": latest_mtm.ts.isoformat()
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
