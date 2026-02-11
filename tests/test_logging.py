"""Tests for structured logging setup."""

from __future__ import annotations

import json
import logging

import structlog

from trading_core.logging import get_logger, setup_logging


class TestSetupLogging:
    def test_json_format(self, capsys):
        setup_logging(level="INFO", log_format="json")
        logger = get_logger("test_json")
        logger.info("test message", asset="BTC")

        captured = capsys.readouterr()
        line = json.loads(captured.err.strip())
        assert line["event"] == "test message"
        assert line["asset"] == "BTC"
        assert line["level"] == "info"
        assert "timestamp" in line

    def test_console_format(self, capsys):
        setup_logging(level="INFO", log_format="console")
        logger = get_logger("test_console")
        logger.info("hello console", strategy="contrarian")

        captured = capsys.readouterr()
        assert "hello console" in captured.err
        assert "contrarian" in captured.err

    def test_log_level_filtering(self, capsys):
        setup_logging(level="WARNING", log_format="json")
        logger = get_logger("test_level")
        logger.info("should be hidden")
        logger.warning("should appear")

        captured = capsys.readouterr()
        assert "should be hidden" not in captured.err
        assert "should appear" in captured.err

    def test_get_logger_with_context(self, capsys):
        setup_logging(level="INFO", log_format="json")
        logger = get_logger("test_ctx", asset="ETH", strategy="funding_rate")
        logger.info("context test")

        captured = capsys.readouterr()
        line = json.loads(captured.err.strip())
        assert line["asset"] == "ETH"
        assert line["strategy"] == "funding_rate"

    def test_contextvars_binding(self, capsys):
        setup_logging(level="INFO", log_format="json")
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id="abc123")

        logger = get_logger("test_ctxvars")
        logger.info("with context var")

        captured = capsys.readouterr()
        line = json.loads(captured.err.strip())
        assert line["request_id"] == "abc123"

        structlog.contextvars.clear_contextvars()
