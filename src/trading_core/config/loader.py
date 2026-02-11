"""Config loader — reads YAML, applies TRADING_* env var overrides."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from trading_core.config.schema import AppConfig


def load_config(path: str | Path | None = None) -> AppConfig:
    """Load config from a YAML file, then apply env var overrides.

    If *path* is None or the file doesn't exist, returns defaults.

    Environment variable overrides:
        TRADING_DATABASE_URL  -> database.url
        TRADING_LOG_LEVEL     -> logging.level
        TRADING_LOG_FORMAT    -> logging.format
    """
    data: dict = {}
    if path is not None:
        p = Path(path)
        if p.exists():
            with open(p) as f:
                data = yaml.safe_load(f) or {}

    # Apply env var overrides
    db_url = os.environ.get("TRADING_DATABASE_URL")
    if db_url:
        data.setdefault("database", {})["url"] = db_url

    log_level = os.environ.get("TRADING_LOG_LEVEL")
    if log_level:
        data.setdefault("logging", {})["level"] = log_level

    log_format = os.environ.get("TRADING_LOG_FORMAT")
    if log_format:
        data.setdefault("logging", {})["format"] = log_format

    return AppConfig.model_validate(data)
