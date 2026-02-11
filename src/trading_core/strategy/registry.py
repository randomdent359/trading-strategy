"""Strategy registry — decorated classes are auto-registered."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from trading_core.strategy.base import Strategy

STRATEGY_REGISTRY: dict[str, type[Strategy]] = {}


def register(cls: type[Strategy]) -> type[Strategy]:
    """Class decorator that adds a strategy to the global registry."""
    if not hasattr(cls, "name") or not cls.name:
        raise ValueError(f"Strategy class {cls.__name__} must define a 'name' attribute")
    if cls.name in STRATEGY_REGISTRY:
        raise ValueError(f"Duplicate strategy name: {cls.name!r}")
    STRATEGY_REGISTRY[cls.name] = cls
    return cls
