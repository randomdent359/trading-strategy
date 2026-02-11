"""Strategy orchestrator — builds snapshots, evaluates strategies, persists signals."""

from trading_core.orchestrator.persistence import persist_signal
from trading_core.orchestrator.snapshot import build_snapshot

__all__ = ["build_snapshot", "persist_signal"]
