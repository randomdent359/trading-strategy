"""Tests for strategy documentation attributes and API endpoint."""

import pytest
from fastapi.testclient import TestClient

from trading_core.strategy import STRATEGY_REGISTRY
from trading_core.strategy.strategies.contrarian import ContrarianPure, ContrarianStrength
from trading_core.strategy.strategies.funding import FundingRate, FundingOI
from trading_core.strategy.strategies.funding_arb import FundingArb
from trading_core.strategy.strategies.momentum import MomentumBreakout
from trading_core.strategy.strategies.rsi import RSIMeanReversion
from trading_core.api.app import app

ALL_STRATEGY_CLASSES = (
    ContrarianPure, ContrarianStrength, FundingRate, FundingOI,
    FundingArb, MomentumBreakout, RSIMeanReversion,
)

EXPECTED_STRATEGIES = [
    "contrarian_pure",
    "contrarian_strength",
    "funding_rate",
    "funding_oi",
    "funding_arb",
    "momentum_breakout",
    "rsi_mean_reversion",
]

REQUIRED_DOC_KEYS = {"thesis", "data", "risk"}


@pytest.fixture(autouse=True)
def _ensure_registry():
    """Repopulate registry if it was cleared by other tests (e.g. test_strategy.py)."""
    for cls in ALL_STRATEGY_CLASSES:
        STRATEGY_REGISTRY.setdefault(cls.name, cls)


# ---------------------------------------------------------------------------
# Unit tests: docs class attribute
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", EXPECTED_STRATEGIES)
def test_strategy_registered(name: str):
    """Every expected strategy is present in the registry."""
    assert name in STRATEGY_REGISTRY


@pytest.mark.parametrize("name", EXPECTED_STRATEGIES)
def test_strategy_docs_keys(name: str):
    """Each strategy has docs with thesis, data, and risk keys."""
    cls = STRATEGY_REGISTRY[name]
    assert isinstance(cls.docs, dict)
    assert set(cls.docs.keys()) == REQUIRED_DOC_KEYS


@pytest.mark.parametrize("name", EXPECTED_STRATEGIES)
def test_strategy_docs_non_empty(name: str):
    """Each docs value is a non-empty string."""
    cls = STRATEGY_REGISTRY[name]
    for key in REQUIRED_DOC_KEYS:
        val = cls.docs[key]
        assert isinstance(val, str), f"{name}.docs[{key!r}] should be str"
        assert len(val) > 0, f"{name}.docs[{key!r}] should be non-empty"


# ---------------------------------------------------------------------------
# API tests: /api/strategies/{name}/docs
# ---------------------------------------------------------------------------


@pytest.fixture()
def client():
    return TestClient(app)


def test_docs_endpoint_returns_structure(client):
    """GET /api/strategies/funding_rate/docs returns expected fields."""
    resp = client.get("/api/strategies/funding_rate/docs")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "funding_rate"
    assert isinstance(data["description"], str)
    assert len(data["description"]) > 0
    assert set(data["docs"].keys()) == REQUIRED_DOC_KEYS
    assert data["assets"] == ["BTC", "ETH", "SOL"]
    assert data["exchanges"] == ["hyperliquid"]
    assert isinstance(data["interval"], str)


def test_docs_endpoint_404_unknown(client):
    """GET /api/strategies/nonexistent/docs returns 404."""
    resp = client.get("/api/strategies/nonexistent/docs")
    assert resp.status_code == 404
