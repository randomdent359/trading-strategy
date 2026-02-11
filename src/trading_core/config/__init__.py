"""Configuration system."""

from trading_core.config.loader import load_config
from trading_core.config.schema import AppConfig

__all__ = ["AppConfig", "load_config"]
