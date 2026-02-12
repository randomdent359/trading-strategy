"""PaperEngine — signal consumption, position management, exits, mark-to-market."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import structlog
from sqlalchemy.orm import Session

from trading_core.config.schema import PaperConfig
from trading_core.db.tables.paper import MarkToMarketRow, PortfolioRow, PositionRow
from trading_core.db.tables.signals import SignalRow
from trading_core.paper.pricing import get_latest_price
from trading_core.paper.sizing import (
    calculate_pnl,
    calculate_position_size,
    calculate_stop_price,
    calculate_take_profit_price,
)

log = structlog.get_logger("paper_engine")


class PaperEngine:
    """Manages paper trading positions driven by strategy signals."""

    def __init__(self, config: PaperConfig, portfolio_id: int) -> None:
        self.config = config
        self.portfolio_id = portfolio_id

    # ── Portfolio ──────────────────────────────────────────────

    @staticmethod
    def ensure_portfolio(session: Session, name: str = "default", initial_capital: float = 10000) -> int:
        """Upsert the named portfolio and return its ID."""
        row = session.query(PortfolioRow).filter(PortfolioRow.name == name).first()
        if row is not None:
            return row.id
        row = PortfolioRow(
            name=name,
            initial_capital=initial_capital,
            created_at=datetime.now(timezone.utc),
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        log.info("portfolio_ensured", portfolio_id=row.id, name=name)
        return row.id

    # ── Signal consumption ────────────────────────────────────

    def consume_signals(self, session: Session) -> list[SignalRow]:
        """Fetch unacted Hyperliquid signals, mark them acted_on, return the list."""
        rows = (
            session.query(SignalRow)
            .filter(
                SignalRow.acted_on == False,  # noqa: E712
                SignalRow.exchange == "hyperliquid",
            )
            .order_by(SignalRow.ts)
            .all()
        )
        for row in rows:
            row.acted_on = True
        if rows:
            session.commit()
            log.info("signals_consumed", count=len(rows))
        return rows

    # ── Position lifecycle ────────────────────────────────────

    def open_position(
        self,
        session: Session,
        signal: SignalRow,
        current_equity: Decimal,
    ) -> PositionRow | None:
        """Open a new position from a signal. Returns None if no price available."""
        price = get_latest_price(session, signal.asset, signal.exchange)
        if price is None:
            log.warning("no_price_for_position", asset=signal.asset)
            return None

        quantity = calculate_position_size(
            entry_price=price,
            equity=current_equity,
            risk_pct=self.config.risk_pct,
            stop_loss_pct=self.config.default_stop_loss_pct,
        )

        now = datetime.now(timezone.utc)
        position = PositionRow(
            portfolio_id=self.portfolio_id,
            strategy=signal.strategy,
            asset=signal.asset,
            exchange=signal.exchange,
            direction=signal.direction,
            entry_price=float(price),
            entry_ts=now,
            quantity=float(quantity),
            status="OPEN",
            signal_id=signal.id,
            metadata_={},
        )
        session.add(position)
        session.commit()
        session.refresh(position)

        log.info(
            "position_opened",
            position_id=position.id,
            strategy=signal.strategy,
            asset=signal.asset,
            direction=signal.direction,
            entry_price=float(price),
            quantity=float(quantity),
        )
        return position

    def check_exits(self, session: Session, now: datetime) -> list[PositionRow]:
        """Check all open positions for stop-loss, take-profit, or timeout exits."""
        open_positions = (
            session.query(PositionRow)
            .filter(
                PositionRow.portfolio_id == self.portfolio_id,
                PositionRow.status == "OPEN",
            )
            .all()
        )

        closed: list[PositionRow] = []
        timeout_delta = timedelta(minutes=self.config.default_timeout_minutes)

        for pos in open_positions:
            price = get_latest_price(session, pos.asset, pos.exchange)
            if price is None:
                continue

            entry = Decimal(str(pos.entry_price))
            stop = calculate_stop_price(pos.direction, entry, self.config.default_stop_loss_pct)
            tp = calculate_take_profit_price(pos.direction, entry, self.config.default_take_profit_pct)

            exit_reason: str | None = None
            exit_price = price

            # Priority: stop_loss → take_profit → timeout
            if pos.direction == "LONG" and price <= stop:
                exit_reason = "stop_loss"
            elif pos.direction == "SHORT" and price >= stop:
                exit_reason = "stop_loss"
            elif pos.direction == "LONG" and price >= tp:
                exit_reason = "take_profit"
            elif pos.direction == "SHORT" and price <= tp:
                exit_reason = "take_profit"
            elif now.replace(tzinfo=None) - pos.entry_ts.replace(tzinfo=None) >= timeout_delta:
                exit_reason = "timeout"

            if exit_reason is not None:
                self.close_position(session, pos, exit_price, exit_reason)
                closed.append(pos)

        return closed

    def close_position(
        self,
        session: Session,
        position: PositionRow,
        exit_price: Decimal,
        exit_reason: str,
    ) -> None:
        """Close a position: calculate P&L, update row fields."""
        entry = Decimal(str(position.entry_price))
        qty = Decimal(str(position.quantity))
        pnl = calculate_pnl(position.direction, entry, exit_price, qty)

        now = datetime.now(timezone.utc)
        position.exit_price = float(exit_price)
        position.exit_ts = now
        position.exit_reason = exit_reason
        position.realised_pnl = float(pnl)
        position.status = "CLOSED"
        session.commit()

        log.info(
            "position_closed",
            position_id=position.id,
            strategy=position.strategy,
            asset=position.asset,
            direction=position.direction,
            exit_reason=exit_reason,
            realised_pnl=float(pnl),
        )

    # ── Equity ────────────────────────────────────────────────

    def get_current_equity(self, session: Session) -> Decimal:
        """Calculate current equity: initial_capital + realised P&L + unrealised P&L."""
        portfolio = session.get(PortfolioRow, self.portfolio_id)
        initial = Decimal(str(portfolio.initial_capital))

        # Sum realised P&L from closed positions
        closed_positions = (
            session.query(PositionRow)
            .filter(
                PositionRow.portfolio_id == self.portfolio_id,
                PositionRow.status == "CLOSED",
            )
            .all()
        )
        realised = sum(
            (Decimal(str(p.realised_pnl)) for p in closed_positions if p.realised_pnl is not None),
            Decimal("0"),
        )

        # Sum unrealised P&L from open positions
        open_positions = (
            session.query(PositionRow)
            .filter(
                PositionRow.portfolio_id == self.portfolio_id,
                PositionRow.status == "OPEN",
            )
            .all()
        )
        unrealised = Decimal("0")
        for pos in open_positions:
            price = get_latest_price(session, pos.asset, pos.exchange)
            if price is not None:
                unrealised += calculate_pnl(
                    pos.direction,
                    Decimal(str(pos.entry_price)),
                    price,
                    Decimal(str(pos.quantity)),
                )

        return initial + realised + unrealised

    # ── Mark-to-market ────────────────────────────────────────

    def write_mark_to_market(self, session: Session, now: datetime) -> None:
        """Snapshot current equity and write a MarkToMarketRow."""
        portfolio = session.get(PortfolioRow, self.portfolio_id)
        initial = Decimal(str(portfolio.initial_capital))

        closed_positions = (
            session.query(PositionRow)
            .filter(
                PositionRow.portfolio_id == self.portfolio_id,
                PositionRow.status == "CLOSED",
            )
            .all()
        )
        realised = sum(
            (Decimal(str(p.realised_pnl)) for p in closed_positions if p.realised_pnl is not None),
            Decimal("0"),
        )

        open_positions = (
            session.query(PositionRow)
            .filter(
                PositionRow.portfolio_id == self.portfolio_id,
                PositionRow.status == "OPEN",
            )
            .all()
        )

        unrealised = Decimal("0")
        breakdown: dict[str, dict] = {}
        for pos in open_positions:
            price = get_latest_price(session, pos.asset, pos.exchange)
            if price is not None:
                pos_pnl = calculate_pnl(
                    pos.direction,
                    Decimal(str(pos.entry_price)),
                    price,
                    Decimal(str(pos.quantity)),
                )
                unrealised += pos_pnl
            else:
                pos_pnl = Decimal("0")

            key = pos.strategy
            if key not in breakdown:
                breakdown[key] = {"unrealised_pnl": 0.0, "open_positions": 0}
            breakdown[key]["unrealised_pnl"] += float(pos_pnl)
            breakdown[key]["open_positions"] += 1

        # Add realised P&L per strategy to breakdown
        for pos in closed_positions:
            key = pos.strategy
            if key not in breakdown:
                breakdown[key] = {"unrealised_pnl": 0.0, "open_positions": 0}
            if "realised_pnl" not in breakdown[key]:
                breakdown[key]["realised_pnl"] = 0.0
            if pos.realised_pnl is not None:
                breakdown[key]["realised_pnl"] += float(pos.realised_pnl)

        total_equity = initial + realised + unrealised

        mtm = MarkToMarketRow(
            portfolio_id=self.portfolio_id,
            ts=now,
            total_equity=float(total_equity),
            unrealised_pnl=float(unrealised),
            realised_pnl=float(realised),
            open_positions=len(open_positions),
            breakdown=breakdown,
        )
        session.add(mtm)
        session.commit()

        log.info(
            "mtm_written",
            total_equity=float(total_equity),
            unrealised_pnl=float(unrealised),
            realised_pnl=float(realised),
            open_positions=len(open_positions),
        )
