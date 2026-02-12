"""PaperEngine — signal consumption, position management, exits, mark-to-market."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

import structlog
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from trading_core.paper.oracle import PriceOracle

from trading_core.config.schema import PaperConfig
from trading_core.db.tables.paper import MarkToMarketRow, PortfolioRow, PositionRow
from trading_core.db.tables.signals import SignalRow
from trading_core.paper.pricing import get_latest_price
from trading_core.paper.risk import RiskTracker, RiskVerdict, evaluate_risk
from trading_core.paper.sizing import (
    apply_slippage,
    calculate_fees,
    calculate_kelly_allocation,
    calculate_pnl,
    calculate_position_size,
    calculate_position_size_kelly,
    calculate_stop_price,
    calculate_take_profit_price,
)

log = structlog.get_logger("paper_engine")


class PaperEngine:
    """Manages paper trading positions driven by strategy signals."""

    def __init__(
        self,
        config: PaperConfig,
        portfolio_id: int,
        oracle: "PriceOracle | None" = None,
    ) -> None:
        self.config = config
        self.portfolio_id = portfolio_id
        self.risk_tracker = RiskTracker(config)
        self.oracle = oracle

    # ── Price helper ──────────────────────────────────────────

    def _get_price(
        self,
        session: Session,
        asset: str,
        exchange: str,
    ) -> Decimal | None:
        """Delegate to oracle if available, otherwise fall back to DB."""
        if self.oracle is not None:
            price = self.oracle.get_price(asset, exchange, session=session)
            if price is not None:
                return price
        return get_latest_price(session, asset, exchange)

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
        """Fetch unacted signals, mark them acted_on, return the list.

        When oracle is present, consumes all exchanges. Otherwise HL-only.
        """
        query = session.query(SignalRow).filter(
            SignalRow.acted_on == False,  # noqa: E712
        )
        if self.oracle is None:
            query = query.filter(SignalRow.exchange == "hyperliquid")
        rows = query.order_by(SignalRow.ts).all()
        for row in rows:
            row.acted_on = True
        if rows:
            session.commit()
            log.info("signals_consumed", count=len(rows))
        return rows

    # ── Risk gate ───────────────────────────────────────────────

    def check_risk(
        self,
        session: Session,
        signal: SignalRow,
        equity: Decimal,
        now: datetime,
    ) -> RiskVerdict:
        """Evaluate all risk controls for a prospective signal."""
        open_positions = (
            session.query(PositionRow)
            .filter(
                PositionRow.portfolio_id == self.portfolio_id,
                PositionRow.status == "OPEN",
            )
            .all()
        )

        # Estimate new position notional value for exposure check
        price = self._get_price(session, signal.asset, signal.exchange)
        if price is None:
            new_value = Decimal("0")
        else:
            confidence = getattr(signal, "confidence", None)
            kelly_alloc = calculate_kelly_allocation(confidence, self.config)
            if kelly_alloc > 0:
                qty = calculate_position_size_kelly(
                    price, equity, kelly_alloc,
                    self.config.risk_pct, self.config.default_stop_loss_pct,
                )
            else:
                qty = calculate_position_size(
                    price, equity, self.config.risk_pct,
                    self.config.default_stop_loss_pct,
                )
            new_value = price * qty

        return evaluate_risk(
            config=self.config,
            tracker=self.risk_tracker,
            strategy=signal.strategy,
            open_positions=open_positions,
            equity=equity,
            new_position_value=new_value,
            now=now,
        )

    # ── Position lifecycle ────────────────────────────────────

    def open_position(
        self,
        session: Session,
        signal: SignalRow,
        current_equity: Decimal,
    ) -> PositionRow | None:
        """Open a new position from a signal. Returns None if no price available."""
        price = self._get_price(session, signal.asset, signal.exchange)
        if price is None:
            log.warning("no_price_for_position", asset=signal.asset)
            return None

        # Apply slippage to entry price
        slippage_pct = self.config.slippage_pct.get(signal.exchange, 0.0)
        actual_entry_price = apply_slippage(price, signal.direction, slippage_pct, is_entry=True)

        confidence = getattr(signal, "confidence", None)
        kelly_alloc = calculate_kelly_allocation(confidence, self.config)
        if kelly_alloc > 0:
            quantity = calculate_position_size_kelly(
                entry_price=actual_entry_price,
                equity=current_equity,
                kelly_allocation=kelly_alloc,
                risk_pct=self.config.risk_pct,
                stop_loss_pct=self.config.default_stop_loss_pct,
            )
        else:
            quantity = calculate_position_size(
                entry_price=actual_entry_price,
                equity=current_equity,
                risk_pct=self.config.risk_pct,
                stop_loss_pct=self.config.default_stop_loss_pct,
            )
        if quantity == 0:
            log.info("zero_quantity_skipped", asset=signal.asset, strategy=signal.strategy)
            return None

        now = datetime.now(timezone.utc)
        position = PositionRow(
            portfolio_id=self.portfolio_id,
            strategy=signal.strategy,
            asset=signal.asset,
            exchange=signal.exchange,
            direction=signal.direction,
            entry_price=float(actual_entry_price),
            entry_ts=now,
            quantity=float(quantity),
            status="OPEN",
            signal_id=signal.id,
            metadata_={
                "raw_price": float(price),
                "slippage_pct": slippage_pct,
            },
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
            entry_price=float(actual_entry_price),
            raw_price=float(price),
            slippage_pct=slippage_pct,
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
            price = self._get_price(session, pos.asset, pos.exchange)
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
        # Apply slippage to exit price
        slippage_pct = self.config.slippage_pct.get(position.exchange, 0.0)
        actual_exit_price = apply_slippage(exit_price, position.direction, slippage_pct, is_entry=False)

        entry = Decimal(str(position.entry_price))
        qty = Decimal(str(position.quantity))

        # Calculate gross P&L
        gross_pnl = calculate_pnl(position.direction, entry, actual_exit_price, qty)

        # Calculate and deduct fees
        fee_pct = self.config.fee_pct.get(position.exchange, 0.0)
        fees = calculate_fees(entry, actual_exit_price, qty, fee_pct)
        net_pnl = gross_pnl - fees

        now = datetime.now(timezone.utc)
        position.exit_price = float(actual_exit_price)
        position.exit_ts = now
        position.exit_reason = exit_reason
        position.realised_pnl = float(net_pnl)
        position.status = "CLOSED"

        # Store fee info in metadata
        if position.metadata_ is None:
            position.metadata_ = {}
        position.metadata_["exit_raw_price"] = float(exit_price)
        position.metadata_["exit_slippage_pct"] = slippage_pct
        position.metadata_["fees"] = float(fees)
        position.metadata_["gross_pnl"] = float(gross_pnl)

        session.commit()

        self.risk_tracker.record_close(position.strategy, float(net_pnl), now)

        log.info(
            "position_closed",
            position_id=position.id,
            strategy=position.strategy,
            asset=position.asset,
            direction=position.direction,
            exit_reason=exit_reason,
            gross_pnl=float(gross_pnl),
            fees=float(fees),
            net_pnl=float(net_pnl),
            exit_raw_price=float(exit_price),
            exit_slippage_pct=slippage_pct,
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
            price = self._get_price(session, pos.asset, pos.exchange)
            if price is not None:
                # Apply slippage to exit price for unrealized P&L calculation
                slippage_pct = self.config.slippage_pct.get(pos.exchange, 0.0)
                exit_price = apply_slippage(price, pos.direction, slippage_pct, is_entry=False)

                # Calculate gross P&L
                gross_pnl = calculate_pnl(
                    pos.direction,
                    Decimal(str(pos.entry_price)),
                    exit_price,
                    Decimal(str(pos.quantity)),
                )

                # Estimate fees (entry fee already paid, exit fee pending)
                fee_pct = self.config.fee_pct.get(pos.exchange, 0.0)
                entry_fee = Decimal(str(pos.entry_price)) * Decimal(str(pos.quantity)) * Decimal(str(fee_pct))
                exit_fee = exit_price * Decimal(str(pos.quantity)) * Decimal(str(fee_pct))
                total_fees = entry_fee + exit_fee

                # Net unrealized P&L
                unrealised += gross_pnl - total_fees

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
            price = self._get_price(session, pos.asset, pos.exchange)
            if price is not None:
                # Apply slippage to exit price for unrealized P&L calculation
                slippage_pct = self.config.slippage_pct.get(pos.exchange, 0.0)
                exit_price = apply_slippage(price, pos.direction, slippage_pct, is_entry=False)

                # Calculate gross P&L
                gross_pnl = calculate_pnl(
                    pos.direction,
                    Decimal(str(pos.entry_price)),
                    exit_price,
                    Decimal(str(pos.quantity)),
                )

                # Estimate fees
                fee_pct = self.config.fee_pct.get(pos.exchange, 0.0)
                entry_fee = Decimal(str(pos.entry_price)) * Decimal(str(pos.quantity)) * Decimal(str(fee_pct))
                exit_fee = exit_price * Decimal(str(pos.quantity)) * Decimal(str(fee_pct))
                total_fees = entry_fee + exit_fee

                # Net unrealized P&L
                pos_pnl = gross_pnl - total_fees
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
