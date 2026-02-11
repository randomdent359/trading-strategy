"""Import all strategy modules to trigger @register decorators."""

from trading_core.strategy.strategies import contrarian  # noqa: F401
from trading_core.strategy.strategies import funding  # noqa: F401
from trading_core.strategy.strategies import funding_arb  # noqa: F401
from trading_core.strategy.strategies import momentum  # noqa: F401
from trading_core.strategy.strategies import rsi  # noqa: F401
