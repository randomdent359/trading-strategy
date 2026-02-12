"""FastAPI application for trading dashboard backend."""

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, func, and_, or_, distinct
from sqlalchemy.orm import Session
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import List, Dict, Optional, Any, Generator
import structlog

from trading_core.db.engine import get_session as _get_session, init_engine
from trading_core.db.tables.signals import SignalRow
from trading_core.db.tables.paper import PositionRow, MarkToMarketRow, PortfolioRow
from trading_core.db.tables.market_data import CandleRow
from trading_core.config.loader import load_config

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


@app.get("/api/strategies")
async def list_strategies(session: Session = Depends(get_db)):
    """List all strategies with current performance metrics."""
    strategies = []
    # Get all unique strategy names from positions
    strategy_names = session.execute(
        select(distinct(PositionRow.strategy))
    ).scalars().all()

    for strategy_name in strategy_names:
        # Calculate metrics for each strategy

        # Total trades (closed positions)
        total_trades = session.execute(
            select(func.count(PositionRow.id))
            .where(
                and_(
                    PositionRow.strategy == strategy_name,
                    PositionRow.status == "CLOSED"
                )
            )
        ).scalar() or 0

        # Win rate
        wins = session.execute(
            select(func.count(PositionRow.id))
            .where(
                and_(
                    PositionRow.strategy == strategy_name,
                    PositionRow.status == "CLOSED",
                    PositionRow.realised_pnl > 0
                )
            )
        ).scalar() or 0

        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0

        # Average win/loss
        avg_win = session.execute(
            select(func.avg(PositionRow.realised_pnl))
            .where(
                and_(
                    PositionRow.strategy == strategy_name,
                    PositionRow.status == "CLOSED",
                    PositionRow.realised_pnl > 0
                )
            )
        ).scalar() or Decimal("0")

        avg_loss = session.execute(
            select(func.avg(PositionRow.realised_pnl))
            .where(
                and_(
                    PositionRow.strategy == strategy_name,
                    PositionRow.status == "CLOSED",
                    PositionRow.realised_pnl < 0
                )
            )
        ).scalar() or Decimal("0")

        # Total P&L
        total_pnl = session.execute(
            select(func.sum(PositionRow.realised_pnl))
            .where(
                and_(
                    PositionRow.strategy == strategy_name,
                    PositionRow.status == "CLOSED"
                )
            )
        ).scalar() or Decimal("0")

        # Profit factor
        gross_profit = session.execute(
            select(func.sum(PositionRow.realised_pnl))
            .where(
                and_(
                    PositionRow.strategy == strategy_name,
                    PositionRow.status == "CLOSED",
                    PositionRow.realised_pnl > 0
                )
            )
        ).scalar() or Decimal("0")

        gross_loss = abs(session.execute(
            select(func.sum(PositionRow.realised_pnl))
            .where(
                and_(
                    PositionRow.strategy == strategy_name,
                    PositionRow.status == "CLOSED",
                    PositionRow.realised_pnl < 0
                )
            )
        ).scalar() or Decimal("0"))

        profit_factor = float(gross_profit / gross_loss) if gross_loss > 0 else 0

        # Check if strategy is enabled in config
        strategy_config = config.strategies.get(strategy_name, {})
        enabled = strategy_config.get("enabled", False)

        strategies.append({
            "name": strategy_name,
            "enabled": enabled,
            "totalTrades": total_trades,
            "winRate": round(win_rate, 2),
            "avgWin": float(avg_win),
            "avgLoss": float(avg_loss),
            "totalPnl": float(total_pnl),
            "profitFactor": round(profit_factor, 2),
        })

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
                "metadata": s.metadata,
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
    query = select(PositionRow).where(PositionRow.strategy == strategy_name)

    if status:
        query = query.where(PositionRow.status == status)

    # Get total count
    total_count = session.execute(
        select(func.count(PositionRow.id))
        .where(PositionRow.strategy == strategy_name)
    ).scalar()

    # Get paginated results
    positions = session.execute(
        query.order_by(PositionRow.entry_ts.desc())
        .limit(limit)
        .offset(offset)
    ).scalars().all()

    return {
        "trades": [
            {
                "id": p.id,
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
                "metadata": p.metadata
            }
            for p in positions
        ],
        "total": total_count,
        "limit": limit,
        "offset": offset
    }


@app.get("/api/equity-curve")
async def get_equity_curve(
    strategy: Optional[str] = None,
    asset: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    interval: str = "1h",
    session: Session = Depends(get_db)
):
    """Get time-series equity data for charting."""
    # Get the default portfolio
    portfolio = session.execute(
        select(PortfolioRow).where(PortfolioRow.name == "default")
    ).scalar_one_or_none()

    if not portfolio:
        raise HTTPException(status_code=404, detail="Portfolio not found")

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

    # Process snapshots based on filters
    equity_data = []
    for snapshot in snapshots:
        data_point = {
            "timestamp": snapshot.ts.isoformat(),
            "totalEquity": float(snapshot.total_equity),
            "unrealisedPnl": float(snapshot.unrealised_pnl),
            "realisedPnl": float(snapshot.realised_pnl),
            "openPositions": snapshot.open_positions
        }

        # If filtering by strategy or asset, extract from breakdown
        if (strategy or asset) and snapshot.breakdown:
            filtered_equity = Decimal("0")

            if strategy and "by_strategy" in snapshot.breakdown:
                strategy_data = snapshot.breakdown["by_strategy"].get(strategy, {})
                filtered_equity = Decimal(str(strategy_data.get("total_pnl", 0)))
            elif asset and "by_asset" in snapshot.breakdown:
                asset_data = snapshot.breakdown["by_asset"].get(asset, {})
                filtered_equity = Decimal(str(asset_data.get("total_pnl", 0)))

            data_point["filteredEquity"] = float(filtered_equity)

        equity_data.append(data_point)

    return {"data": equity_data}


@app.get("/api/positions/open")
async def get_open_positions(session: Session = Depends(get_db)):
    """Get currently open positions with unrealized P&L."""
    positions = session.execute(
        select(PositionRow)
        .where(PositionRow.status == "OPEN")
        .order_by(PositionRow.entry_ts.desc())
    ).scalars().all()

    # Get current prices for each asset
    current_prices = {}
    for position in positions:
        if position.asset not in current_prices:
            # Get latest candle for this asset
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

    # Calculate unrealized P&L
    open_positions = []
    for position in positions:
        current_price = current_prices.get(position.asset)

        if current_price:
            if position.direction == "LONG":
                unrealised_pnl = (current_price - position.entry_price) * position.quantity
            else:  # SHORT
                unrealised_pnl = (position.entry_price - current_price) * position.quantity
        else:
            unrealised_pnl = Decimal("0")

        open_positions.append({
            "id": position.id,
            "strategy": position.strategy,
            "asset": position.asset,
            "exchange": position.exchange,
            "direction": position.direction,
            "entryPrice": float(position.entry_price),
            "entryTime": position.entry_ts.isoformat(),
            "quantity": float(position.quantity),
            "currentPrice": float(current_price) if current_price else None,
            "unrealisedPnl": float(unrealised_pnl),
            "metadata": position.metadata
        })

    return {"positions": open_positions}


@app.get("/api/assets/{asset}/performance")
async def get_asset_performance(asset: str, session: Session = Depends(get_db)):
    """Get per-asset P&L across all strategies."""
    # Get all closed positions for this asset
    positions = session.execute(
        select(PositionRow)
        .where(
            and_(
                PositionRow.asset == asset,
                PositionRow.status == "CLOSED"
            )
        )
    ).scalars().all()

    # Group by strategy
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

    # Calculate averages
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
    """Get portfolio-level metrics."""
    # Get default portfolio
    portfolio = session.execute(
        select(PortfolioRow).where(PortfolioRow.name == "default")
    ).scalar_one_or_none()

    if not portfolio:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    # Get latest mark-to-market
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
            "maxDrawdown": 0
        }

    # Calculate daily returns for Sharpe/Sortino
    # Get MTM snapshots from last 30 days
    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
    recent_snapshots = session.execute(
        select(MarkToMarketRow)
        .where(
            and_(
                MarkToMarketRow.portfolio_id == portfolio.id,
                MarkToMarketRow.ts >= thirty_days_ago
            )
        )
        .order_by(MarkToMarketRow.ts)
    ).scalars().all()

    # Calculate daily returns
    daily_returns = []
    if len(recent_snapshots) > 1:
        for i in range(1, len(recent_snapshots)):
            prev_equity = recent_snapshots[i-1].total_equity
            curr_equity = recent_snapshots[i].total_equity

            if prev_equity > 0:
                daily_return = float((curr_equity - prev_equity) / prev_equity)
                daily_returns.append(daily_return)

    # Calculate metrics
    sharpe_ratio = 0
    sortino_ratio = 0
    max_drawdown = 0

    if daily_returns:
        import numpy as np

        returns_array = np.array(daily_returns)
        mean_return = np.mean(returns_array)
        std_return = np.std(returns_array)

        if std_return > 0:
            sharpe_ratio = mean_return / std_return * np.sqrt(252)  # Annualized

        # Sortino ratio (downside deviation)
        negative_returns = returns_array[returns_array < 0]
        if len(negative_returns) > 0:
            downside_std = np.std(negative_returns)
            if downside_std > 0:
                sortino_ratio = mean_return / downside_std * np.sqrt(252)

    # Calculate max drawdown
    if recent_snapshots:
        peak_equity = recent_snapshots[0].total_equity
        max_dd_pct = 0

        for snapshot in recent_snapshots:
            if snapshot.total_equity > peak_equity:
                peak_equity = snapshot.total_equity

            drawdown = (peak_equity - snapshot.total_equity) / peak_equity
            if drawdown > max_dd_pct:
                max_dd_pct = drawdown

        max_drawdown = float(max_dd_pct * 100)  # As percentage

    # Get current day's P&L
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
        "sharpeRatio": round(sharpe_ratio, 2),
        "sortinoRatio": round(sortino_ratio, 2),
        "maxDrawdown": round(max_drawdown, 2),
        "lastUpdate": latest_mtm.ts.isoformat()
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)