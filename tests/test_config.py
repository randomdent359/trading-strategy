"""Tests for configuration loading."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from trading_core.config import AppConfig, load_config


class TestAppConfig:
    def test_defaults(self):
        cfg = AppConfig()
        assert cfg.assets == ["BTC", "ETH", "SOL"]
        assert cfg.database.url == "postgresql://trading:trading@localhost:5432/trading"
        assert cfg.logging.level == "INFO"
        assert cfg.logging.format == "json"
        assert cfg.paper.initial_capital == 10000

    def test_custom_assets(self):
        cfg = AppConfig(assets=["BTC"])
        assert cfg.assets == ["BTC"]


class TestLoadConfig:
    def test_load_example_config(self):
        cfg = load_config("config.yaml.example")
        assert cfg.assets == ["BTC", "ETH", "SOL"]
        assert cfg.exchanges["hyperliquid"].poll_interval_s == 5
        assert cfg.strategies["contrarian_pure"].enabled is True
        assert cfg.strategies["contrarian_pure"].params["threshold"] == 0.72

    def test_load_nonexistent_file_returns_defaults(self):
        cfg = load_config("/tmp/nonexistent_config_12345.yaml")
        assert cfg.assets == ["BTC", "ETH", "SOL"]
        assert cfg.database.url == "postgresql://trading:trading@localhost:5432/trading"

    def test_load_none_returns_defaults(self):
        cfg = load_config(None)
        assert cfg.assets == ["BTC", "ETH", "SOL"]

    def test_env_override_database_url(self, monkeypatch):
        monkeypatch.setenv("TRADING_DATABASE_URL", "postgresql://test:test@db:5432/testdb")
        cfg = load_config(None)
        assert cfg.database.url == "postgresql://test:test@db:5432/testdb"

    def test_env_override_log_level(self, monkeypatch):
        monkeypatch.setenv("TRADING_LOG_LEVEL", "DEBUG")
        cfg = load_config(None)
        assert cfg.logging.level == "DEBUG"

    def test_env_override_log_format(self, monkeypatch):
        monkeypatch.setenv("TRADING_LOG_FORMAT", "console")
        cfg = load_config(None)
        assert cfg.logging.format == "console"

    def test_env_overrides_yaml_values(self, monkeypatch):
        monkeypatch.setenv("TRADING_DATABASE_URL", "postgresql://override@host/db")
        cfg = load_config("config.yaml.example")
        assert cfg.database.url == "postgresql://override@host/db"
        # Non-overridden values preserved
        assert cfg.exchanges["hyperliquid"].poll_interval_s == 5

    def test_load_minimal_yaml(self, tmp_path):
        p = tmp_path / "minimal.yaml"
        p.write_text("assets: [BTC]\n")
        cfg = load_config(p)
        assert cfg.assets == ["BTC"]
        # Defaults still apply for unspecified sections
        assert cfg.database.url == "postgresql://trading:trading@localhost:5432/trading"
