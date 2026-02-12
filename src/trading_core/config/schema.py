"""Configuration schema — Pydantic models for config.yaml."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ExchangeConfig(BaseModel):
    base_url: str
    poll_interval_s: int = 5


class DatabaseConfig(BaseModel):
    url: str = "postgresql://trading:trading@localhost:5432/trading"


class StrategyParams(BaseModel):
    enabled: bool = True
    params: dict[str, float | int | str | bool] = Field(default_factory=dict)


class LoggingConfig(BaseModel):
    level: str = "INFO"
    format: str = "json"


class PaperConfig(BaseModel):
    initial_capital: float = 10000
    risk_pct: float = 0.02
    default_stop_loss_pct: float = 0.02
    default_take_profit_pct: float = 0.04
    default_timeout_minutes: int = 60
    # Risk controls
    max_positions_per_strategy: int = 3
    max_total_exposure_pct: float = 0.50
    max_daily_loss_per_strategy: float = 500.0
    cooldown_after_loss_minutes: int = 5
    # Kelly criterion
    kelly_enabled: bool = True
    kelly_safety_factor: float = 0.5


class AppConfig(BaseModel):
    assets: list[str] = Field(default_factory=lambda: ["BTC", "ETH", "SOL"])
    exchanges: dict[str, ExchangeConfig] = Field(default_factory=dict)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    strategies: dict[str, StrategyParams] = Field(default_factory=dict)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    paper: PaperConfig = Field(default_factory=PaperConfig)
