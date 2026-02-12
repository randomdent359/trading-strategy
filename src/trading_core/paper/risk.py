"""Risk controls — in-memory per-strategy tracking for paper trading."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

from trading_core.config.schema import PaperConfig
from trading_core.db.tables.paper import PositionRow


@dataclass
class RiskVerdict:
    """Result of a risk check — allowed or rejected with a reason."""

    allowed: bool
    reason: str = ""


@dataclass
class _StrategyState:
    """Per-strategy accumulated risk state."""

    daily_loss: float = 0.0
    daily_wins: float = 0.0
    last_loss_ts: datetime | None = None
    day_key: str = ""  # "YYYY-MM-DD" for reset detection


class RiskTracker:
    """In-memory per-strategy risk state. Resets on process restart."""

    def __init__(self, config: PaperConfig) -> None:
        self.config = config
        self._states: dict[str, _StrategyState] = defaultdict(_StrategyState)

    def _get_state(self, strategy: str, now: datetime) -> _StrategyState:
        """Get or create strategy state, resetting on new UTC day."""
        state = self._states[strategy]
        today = now.strftime("%Y-%m-%d")
        if state.day_key != today:
            state.daily_loss = 0.0
            state.daily_wins = 0.0
            state.day_key = today
        return state

    def record_close(self, strategy: str, pnl: float, ts: datetime) -> None:
        """Record a position close — accumulate daily P&L and set cooldown on loss."""
        state = self._get_state(strategy, ts)
        if pnl < 0:
            state.daily_loss += abs(pnl)
            state.last_loss_ts = ts
        else:
            state.daily_wins += pnl

    def is_strategy_paused(self, strategy: str, now: datetime) -> bool:
        """True if strategy's net daily loss exceeds the configured limit."""
        state = self._get_state(strategy, now)
        net_loss = state.daily_loss - state.daily_wins
        return net_loss > self.config.max_daily_loss_per_strategy

    def is_in_cooldown(self, strategy: str, now: datetime) -> bool:
        """True if strategy had a recent loss within the cooldown window."""
        state = self._get_state(strategy, now)
        if state.last_loss_ts is None:
            return False
        elapsed = (now - state.last_loss_ts).total_seconds()
        return elapsed < self.config.cooldown_after_loss_minutes * 60


# ── Pure check functions ──────────────────────────────────────


def check_max_positions_per_strategy(
    strategy: str,
    open_positions: list[PositionRow],
    limit: int,
) -> RiskVerdict:
    """Reject if strategy already has >= limit open positions."""
    count = sum(1 for p in open_positions if p.strategy == strategy)
    if count >= limit:
        return RiskVerdict(
            allowed=False,
            reason=f"max_positions_per_strategy ({count}/{limit})",
        )
    return RiskVerdict(allowed=True)


def check_max_total_exposure(
    open_positions: list[PositionRow],
    equity: Decimal,
    new_position_value: Decimal,
    limit_pct: float,
) -> RiskVerdict:
    """Reject if total notional exposure would exceed limit_pct of equity."""
    current_exposure = sum(
        Decimal(str(p.entry_price)) * Decimal(str(p.quantity))
        for p in open_positions
    )
    total = current_exposure + new_position_value
    limit_value = equity * Decimal(str(limit_pct))
    if total > limit_value:
        return RiskVerdict(
            allowed=False,
            reason=f"max_total_exposure ({float(total):.0f}/{float(limit_value):.0f})",
        )
    return RiskVerdict(allowed=True)


def evaluate_risk(
    config: PaperConfig,
    tracker: RiskTracker,
    strategy: str,
    open_positions: list[PositionRow],
    equity: Decimal,
    new_position_value: Decimal,
    now: datetime,
) -> RiskVerdict:
    """Composite risk check — returns first failing verdict or ALLOW."""
    if tracker.is_strategy_paused(strategy, now):
        return RiskVerdict(
            allowed=False,
            reason="daily_loss_limit_exceeded",
        )

    if tracker.is_in_cooldown(strategy, now):
        return RiskVerdict(
            allowed=False,
            reason="cooldown_active",
        )

    verdict = check_max_positions_per_strategy(
        strategy, open_positions, config.max_positions_per_strategy,
    )
    if not verdict.allowed:
        return verdict

    verdict = check_max_total_exposure(
        open_positions, equity, new_position_value, config.max_total_exposure_pct,
    )
    if not verdict.allowed:
        return verdict

    return RiskVerdict(allowed=True)
