"""DB query bridge — fetches rows and delegates to formulas.py."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session

from trading_core.db.tables.accounts import (
    AccountMarkToMarketRow,
    AccountPositionRow,
    PortfolioMemberRow,
)
from trading_core.db.tables.paper import PositionRow, MarkToMarketRow
from trading_core.metrics.formulas import (
    StrategyMetrics,
    avg_hold_time_minutes,
    expectancy,
    max_drawdown,
    profit_factor,
    sharpe_ratio,
    sortino_ratio,
    win_rate,
)


def _to_float(val: Decimal | float | None, default: float = 0.0) -> float:
    """Safely cast a Decimal/float/None to float."""
    if val is None:
        return default
    return float(val)


def compute_strategy_metrics(
    session: Session,
    strategy: str,
    portfolio_id: int | None = None,
    account_id: int | None = None,
) -> StrategyMetrics:
    """Compute all metrics for a single strategy from closed positions.

    Queries AccountPositionRow (new schema) by default.
    Falls back to PositionRow (old schema) only when portfolio_id is given.
    """
    if portfolio_id is not None and account_id is None:
        # Legacy path — query old trading_paper schema
        return _compute_strategy_metrics_legacy(session, strategy, portfolio_id)

    # New path — query trading_accounts schema
    base_filter = [
        AccountPositionRow.strategy == strategy,
        AccountPositionRow.status == "CLOSED",
    ]
    if account_id is not None:
        base_filter.append(AccountPositionRow.account_id == account_id)

    # Total trades
    total = session.execute(
        select(func.count(AccountPositionRow.id)).where(and_(*base_filter))
    ).scalar() or 0

    if total == 0:
        return StrategyMetrics()

    # Wins
    wins_count = session.execute(
        select(func.count(AccountPositionRow.id)).where(
            and_(*base_filter, AccountPositionRow.realised_pnl > 0)
        )
    ).scalar() or 0

    # Avg win / avg loss
    avg_w = _to_float(session.execute(
        select(func.avg(AccountPositionRow.realised_pnl)).where(
            and_(*base_filter, AccountPositionRow.realised_pnl > 0)
        )
    ).scalar())

    avg_l = _to_float(session.execute(
        select(func.avg(AccountPositionRow.realised_pnl)).where(
            and_(*base_filter, AccountPositionRow.realised_pnl < 0)
        )
    ).scalar())

    # Total P&L
    total_pnl = _to_float(session.execute(
        select(func.sum(AccountPositionRow.realised_pnl)).where(and_(*base_filter))
    ).scalar())

    # Gross profit / loss for profit factor
    gross_profit = _to_float(session.execute(
        select(func.sum(AccountPositionRow.realised_pnl)).where(
            and_(*base_filter, AccountPositionRow.realised_pnl > 0)
        )
    ).scalar())

    gross_loss = abs(_to_float(session.execute(
        select(func.sum(AccountPositionRow.realised_pnl)).where(
            and_(*base_filter, AccountPositionRow.realised_pnl < 0)
        )
    ).scalar()))

    # Per-trade returns for Sharpe / Sortino
    positions = session.execute(
        select(AccountPositionRow).where(and_(*base_filter)).order_by(AccountPositionRow.entry_ts)
    ).scalars().all()

    returns = []
    hold_seconds = []
    cumulative_pnl = []
    running = 0.0

    for pos in positions:
        entry_notional = _to_float(pos.entry_price) * _to_float(pos.quantity)
        pnl = _to_float(pos.realised_pnl)
        if entry_notional > 0:
            returns.append(pnl / entry_notional)
        running += pnl
        cumulative_pnl.append(running)
        if pos.exit_ts and pos.entry_ts:
            hold_seconds.append((pos.exit_ts - pos.entry_ts).total_seconds())

    wr = win_rate(wins_count, total)

    return StrategyMetrics(
        total_trades=total,
        wins=wins_count,
        total_pnl=total_pnl,
        avg_win=avg_w,
        avg_loss=avg_l,
        win_rate=wr,
        profit_factor=profit_factor(gross_profit, gross_loss),
        expectancy=expectancy(wr, avg_w, avg_l),
        sharpe_ratio=sharpe_ratio(returns),
        sortino_ratio=sortino_ratio(returns),
        max_drawdown=max_drawdown(cumulative_pnl) if cumulative_pnl else 0.0,
        avg_hold_minutes=avg_hold_time_minutes(hold_seconds),
    )


def _compute_strategy_metrics_legacy(
    session: Session,
    strategy: str,
    portfolio_id: int,
) -> StrategyMetrics:
    """Legacy path: compute metrics from trading_paper.positions."""
    base_filter = [
        PositionRow.strategy == strategy,
        PositionRow.status == "CLOSED",
        PositionRow.portfolio_id == portfolio_id,
    ]

    total = session.execute(
        select(func.count(PositionRow.id)).where(and_(*base_filter))
    ).scalar() or 0

    if total == 0:
        return StrategyMetrics()

    wins_count = session.execute(
        select(func.count(PositionRow.id)).where(
            and_(*base_filter, PositionRow.realised_pnl > 0)
        )
    ).scalar() or 0

    avg_w = _to_float(session.execute(
        select(func.avg(PositionRow.realised_pnl)).where(
            and_(*base_filter, PositionRow.realised_pnl > 0)
        )
    ).scalar())

    avg_l = _to_float(session.execute(
        select(func.avg(PositionRow.realised_pnl)).where(
            and_(*base_filter, PositionRow.realised_pnl < 0)
        )
    ).scalar())

    total_pnl = _to_float(session.execute(
        select(func.sum(PositionRow.realised_pnl)).where(and_(*base_filter))
    ).scalar())

    gross_profit = _to_float(session.execute(
        select(func.sum(PositionRow.realised_pnl)).where(
            and_(*base_filter, PositionRow.realised_pnl > 0)
        )
    ).scalar())

    gross_loss = abs(_to_float(session.execute(
        select(func.sum(PositionRow.realised_pnl)).where(
            and_(*base_filter, PositionRow.realised_pnl < 0)
        )
    ).scalar()))

    positions = session.execute(
        select(PositionRow).where(and_(*base_filter)).order_by(PositionRow.entry_ts)
    ).scalars().all()

    returns = []
    hold_seconds = []
    cumulative_pnl = []
    running = 0.0

    for pos in positions:
        entry_notional = _to_float(pos.entry_price) * _to_float(pos.quantity)
        pnl = _to_float(pos.realised_pnl)
        if entry_notional > 0:
            returns.append(pnl / entry_notional)
        running += pnl
        cumulative_pnl.append(running)
        if pos.exit_ts and pos.entry_ts:
            hold_seconds.append((pos.exit_ts - pos.entry_ts).total_seconds())

    wr = win_rate(wins_count, total)

    return StrategyMetrics(
        total_trades=total,
        wins=wins_count,
        total_pnl=total_pnl,
        avg_win=avg_w,
        avg_loss=avg_l,
        win_rate=wr,
        profit_factor=profit_factor(gross_profit, gross_loss),
        expectancy=expectancy(wr, avg_w, avg_l),
        sharpe_ratio=sharpe_ratio(returns),
        sortino_ratio=sortino_ratio(returns),
        max_drawdown=max_drawdown(cumulative_pnl) if cumulative_pnl else 0.0,
        avg_hold_minutes=avg_hold_time_minutes(hold_seconds),
    )


def compute_portfolio_metrics(
    session: Session,
    portfolio_id: int,
) -> StrategyMetrics:
    """Compute portfolio-level metrics using MTM equity series + closed positions.

    Legacy path — uses trading_paper schema.
    """
    base_filter = [
        PositionRow.portfolio_id == portfolio_id,
        PositionRow.status == "CLOSED",
    ]

    total = session.execute(
        select(func.count(PositionRow.id)).where(and_(*base_filter))
    ).scalar() or 0

    wins_count = session.execute(
        select(func.count(PositionRow.id)).where(
            and_(*base_filter, PositionRow.realised_pnl > 0)
        )
    ).scalar() or 0

    avg_w = _to_float(session.execute(
        select(func.avg(PositionRow.realised_pnl)).where(
            and_(*base_filter, PositionRow.realised_pnl > 0)
        )
    ).scalar())

    avg_l = _to_float(session.execute(
        select(func.avg(PositionRow.realised_pnl)).where(
            and_(*base_filter, PositionRow.realised_pnl < 0)
        )
    ).scalar())

    total_pnl = _to_float(session.execute(
        select(func.sum(PositionRow.realised_pnl)).where(and_(*base_filter))
    ).scalar())

    gross_profit = _to_float(session.execute(
        select(func.sum(PositionRow.realised_pnl)).where(
            and_(*base_filter, PositionRow.realised_pnl > 0)
        )
    ).scalar())

    gross_loss = abs(_to_float(session.execute(
        select(func.sum(PositionRow.realised_pnl)).where(
            and_(*base_filter, PositionRow.realised_pnl < 0)
        )
    ).scalar()))

    positions = session.execute(
        select(PositionRow).where(and_(*base_filter)).order_by(PositionRow.entry_ts)
    ).scalars().all()

    hold_seconds = []
    for pos in positions:
        if pos.exit_ts and pos.entry_ts:
            hold_seconds.append((pos.exit_ts - pos.entry_ts).total_seconds())

    mtm_rows = session.execute(
        select(MarkToMarketRow)
        .where(MarkToMarketRow.portfolio_id == portfolio_id)
        .order_by(MarkToMarketRow.ts)
    ).scalars().all()

    returns = []
    equity_series = []
    for row in mtm_rows:
        equity_series.append(_to_float(row.total_equity))

    if len(equity_series) > 1:
        for i in range(1, len(equity_series)):
            prev = equity_series[i - 1]
            if prev > 0:
                returns.append((equity_series[i] - prev) / prev)

    wr = win_rate(wins_count, total)

    return StrategyMetrics(
        total_trades=total,
        wins=wins_count,
        total_pnl=total_pnl,
        avg_win=avg_w,
        avg_loss=avg_l,
        win_rate=wr,
        profit_factor=profit_factor(gross_profit, gross_loss),
        expectancy=expectancy(wr, avg_w, avg_l),
        sharpe_ratio=sharpe_ratio(returns),
        sortino_ratio=sortino_ratio(returns),
        max_drawdown=max_drawdown(equity_series),
        avg_hold_minutes=avg_hold_time_minutes(hold_seconds),
    )


def compute_account_metrics(
    session: Session,
    account_id: int,
) -> StrategyMetrics:
    """Compute account-level metrics using account MTM equity series + closed positions."""
    base_filter = [
        AccountPositionRow.account_id == account_id,
        AccountPositionRow.status == "CLOSED",
    ]

    total = session.execute(
        select(func.count(AccountPositionRow.id)).where(and_(*base_filter))
    ).scalar() or 0

    wins_count = session.execute(
        select(func.count(AccountPositionRow.id)).where(
            and_(*base_filter, AccountPositionRow.realised_pnl > 0)
        )
    ).scalar() or 0

    avg_w = _to_float(session.execute(
        select(func.avg(AccountPositionRow.realised_pnl)).where(
            and_(*base_filter, AccountPositionRow.realised_pnl > 0)
        )
    ).scalar())

    avg_l = _to_float(session.execute(
        select(func.avg(AccountPositionRow.realised_pnl)).where(
            and_(*base_filter, AccountPositionRow.realised_pnl < 0)
        )
    ).scalar())

    total_pnl = _to_float(session.execute(
        select(func.sum(AccountPositionRow.realised_pnl)).where(and_(*base_filter))
    ).scalar())

    gross_profit = _to_float(session.execute(
        select(func.sum(AccountPositionRow.realised_pnl)).where(
            and_(*base_filter, AccountPositionRow.realised_pnl > 0)
        )
    ).scalar())

    gross_loss = abs(_to_float(session.execute(
        select(func.sum(AccountPositionRow.realised_pnl)).where(
            and_(*base_filter, AccountPositionRow.realised_pnl < 0)
        )
    ).scalar()))

    positions = session.execute(
        select(AccountPositionRow).where(and_(*base_filter)).order_by(AccountPositionRow.entry_ts)
    ).scalars().all()

    hold_seconds = []
    for pos in positions:
        if pos.exit_ts and pos.entry_ts:
            hold_seconds.append((pos.exit_ts - pos.entry_ts).total_seconds())

    mtm_rows = session.execute(
        select(AccountMarkToMarketRow)
        .where(AccountMarkToMarketRow.account_id == account_id)
        .order_by(AccountMarkToMarketRow.ts)
    ).scalars().all()

    returns = []
    equity_series = []
    for row in mtm_rows:
        equity_series.append(_to_float(row.total_equity))

    if len(equity_series) > 1:
        for i in range(1, len(equity_series)):
            prev = equity_series[i - 1]
            if prev > 0:
                returns.append((equity_series[i] - prev) / prev)

    wr = win_rate(wins_count, total)

    return StrategyMetrics(
        total_trades=total,
        wins=wins_count,
        total_pnl=total_pnl,
        avg_win=avg_w,
        avg_loss=avg_l,
        win_rate=wr,
        profit_factor=profit_factor(gross_profit, gross_loss),
        expectancy=expectancy(wr, avg_w, avg_l),
        sharpe_ratio=sharpe_ratio(returns),
        sortino_ratio=sortino_ratio(returns),
        max_drawdown=max_drawdown(equity_series),
        avg_hold_minutes=avg_hold_time_minutes(hold_seconds),
    )


def compute_portfolio_group_metrics(
    session: Session,
    portfolio_id: int,
) -> StrategyMetrics:
    """Aggregate metrics across all accounts in a portfolio group."""
    # Get account IDs in this portfolio
    account_ids = session.execute(
        select(PortfolioMemberRow.account_id)
        .where(PortfolioMemberRow.portfolio_id == portfolio_id)
    ).scalars().all()

    if not account_ids:
        return StrategyMetrics()

    base_filter = [
        AccountPositionRow.account_id.in_(account_ids),
        AccountPositionRow.status == "CLOSED",
    ]

    total = session.execute(
        select(func.count(AccountPositionRow.id)).where(and_(*base_filter))
    ).scalar() or 0

    wins_count = session.execute(
        select(func.count(AccountPositionRow.id)).where(
            and_(*base_filter, AccountPositionRow.realised_pnl > 0)
        )
    ).scalar() or 0

    avg_w = _to_float(session.execute(
        select(func.avg(AccountPositionRow.realised_pnl)).where(
            and_(*base_filter, AccountPositionRow.realised_pnl > 0)
        )
    ).scalar())

    avg_l = _to_float(session.execute(
        select(func.avg(AccountPositionRow.realised_pnl)).where(
            and_(*base_filter, AccountPositionRow.realised_pnl < 0)
        )
    ).scalar())

    total_pnl = _to_float(session.execute(
        select(func.sum(AccountPositionRow.realised_pnl)).where(and_(*base_filter))
    ).scalar())

    gross_profit = _to_float(session.execute(
        select(func.sum(AccountPositionRow.realised_pnl)).where(
            and_(*base_filter, AccountPositionRow.realised_pnl > 0)
        )
    ).scalar())

    gross_loss = abs(_to_float(session.execute(
        select(func.sum(AccountPositionRow.realised_pnl)).where(
            and_(*base_filter, AccountPositionRow.realised_pnl < 0)
        )
    ).scalar()))

    positions = session.execute(
        select(AccountPositionRow).where(and_(*base_filter)).order_by(AccountPositionRow.entry_ts)
    ).scalars().all()

    hold_seconds = []
    for pos in positions:
        if pos.exit_ts and pos.entry_ts:
            hold_seconds.append((pos.exit_ts - pos.entry_ts).total_seconds())

    # Aggregate MTM across all member accounts
    mtm_rows = session.execute(
        select(AccountMarkToMarketRow)
        .where(AccountMarkToMarketRow.account_id.in_(account_ids))
        .order_by(AccountMarkToMarketRow.ts)
    ).scalars().all()

    # Group by timestamp and sum equities
    equity_by_ts: dict[str, float] = {}
    for row in mtm_rows:
        ts_key = row.ts.isoformat()
        equity_by_ts[ts_key] = equity_by_ts.get(ts_key, 0.0) + _to_float(row.total_equity)

    equity_series = list(equity_by_ts.values())
    returns = []
    if len(equity_series) > 1:
        for i in range(1, len(equity_series)):
            prev = equity_series[i - 1]
            if prev > 0:
                returns.append((equity_series[i] - prev) / prev)

    wr = win_rate(wins_count, total)

    return StrategyMetrics(
        total_trades=total,
        wins=wins_count,
        total_pnl=total_pnl,
        avg_win=avg_w,
        avg_loss=avg_l,
        win_rate=wr,
        profit_factor=profit_factor(gross_profit, gross_loss),
        expectancy=expectancy(wr, avg_w, avg_l),
        sharpe_ratio=sharpe_ratio(returns),
        sortino_ratio=sortino_ratio(returns),
        max_drawdown=max_drawdown(equity_series),
        avg_hold_minutes=avg_hold_time_minutes(hold_seconds),
    )
