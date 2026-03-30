"""Tests for the trade log module."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from cashflow_engine.api.app import app
from cashflow_engine.core import trade_log

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_rate_store():
    from cashflow_engine.api.app import _rate_store
    _rate_store.clear()
    yield
    _rate_store.clear()


@pytest.fixture(autouse=True)
def isolated_trades_db(tmp_path, monkeypatch):
    """Point the trades log at a fresh temp file for every test."""
    monkeypatch.setenv("TRADES_DB_PATH", str(tmp_path / "trades.json"))


def _sample_trade(**overrides) -> dict:
    defaults = dict(
        module="trading",
        symbol="BTC/USDT",
        side="buy",
        amount=0.02,
        price=50000.0,
        exchange="binance",
        dry_run=True,
        order_id="order-1",
    )
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# append_trade
# ---------------------------------------------------------------------------


def test_append_trade_creates_file(tmp_path, monkeypatch):
    path = tmp_path / "trades.json"
    monkeypatch.setenv("TRADES_DB_PATH", str(path))
    assert not path.exists()
    trade_log.append_trade(**_sample_trade())
    assert path.exists()


def test_append_trade_record_fields(tmp_path, monkeypatch):
    path = tmp_path / "trades.json"
    monkeypatch.setenv("TRADES_DB_PATH", str(path))
    record = trade_log.append_trade(**_sample_trade(order_id="abc-123"))
    assert record["module"] == "trading"
    assert record["symbol"] == "BTC/USDT"
    assert record["side"] == "buy"
    assert record["amount"] == 0.02
    assert record["price"] == 50000.0
    assert record["exchange"] == "binance"
    assert record["dry_run"] is True
    assert record["order_id"] == "abc-123"
    assert "timestamp" in record


def test_append_trade_no_order_id(tmp_path, monkeypatch):
    path = tmp_path / "trades.json"
    monkeypatch.setenv("TRADES_DB_PATH", str(path))
    record = trade_log.append_trade(**_sample_trade(order_id=None))
    assert record["order_id"] is None


def test_append_trade_accumulates(tmp_path, monkeypatch):
    path = tmp_path / "trades.json"
    monkeypatch.setenv("TRADES_DB_PATH", str(path))
    trade_log.append_trade(**_sample_trade(side="buy"))
    trade_log.append_trade(**_sample_trade(side="sell"))
    trade_log.append_trade(**_sample_trade(side="buy"))
    with path.open() as f:
        records = json.load(f)
    assert len(records) == 3


def test_append_trade_atomic_no_tmp_left(tmp_path, monkeypatch):
    path = tmp_path / "trades.json"
    monkeypatch.setenv("TRADES_DB_PATH", str(path))
    trade_log.append_trade(**_sample_trade())
    tmp = path.with_suffix(".tmp")
    assert not tmp.exists()


def test_append_trade_arbitrage_module(tmp_path, monkeypatch):
    path = tmp_path / "trades.json"
    monkeypatch.setenv("TRADES_DB_PATH", str(path))
    record = trade_log.append_trade(
        module="arbitrage",
        symbol="ETH/USDT",
        side="buy",
        amount=1.0,
        price=3000.0,
        exchange="coinbase",
        dry_run=False,
        order_id="arb-42",
    )
    assert record["module"] == "arbitrage"
    assert record["exchange"] == "coinbase"
    assert record["dry_run"] is False


# ---------------------------------------------------------------------------
# read_trades
# ---------------------------------------------------------------------------


def test_read_trades_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADES_DB_PATH", str(tmp_path / "trades.json"))
    assert trade_log.read_trades() == []


def test_read_trades_newest_first(tmp_path, monkeypatch):
    path = tmp_path / "trades.json"
    monkeypatch.setenv("TRADES_DB_PATH", str(path))
    trade_log.append_trade(**_sample_trade(side="buy"))
    trade_log.append_trade(**_sample_trade(side="sell"))
    records = trade_log.read_trades()
    assert records[0]["side"] == "sell"
    assert records[1]["side"] == "buy"


def test_read_trades_limit(tmp_path, monkeypatch):
    path = tmp_path / "trades.json"
    monkeypatch.setenv("TRADES_DB_PATH", str(path))
    for _ in range(10):
        trade_log.append_trade(**_sample_trade())
    assert len(trade_log.read_trades(limit=3)) == 3


def test_read_trades_offset(tmp_path, monkeypatch):
    path = tmp_path / "trades.json"
    monkeypatch.setenv("TRADES_DB_PATH", str(path))
    for i in range(5):
        trade_log.append_trade(**_sample_trade(price=float(i)))
    # newest first: prices 4, 3, 2, 1, 0
    page1 = trade_log.read_trades(limit=2, offset=0)
    page2 = trade_log.read_trades(limit=2, offset=2)
    assert page1[0]["price"] == 4.0
    assert page2[0]["price"] == 2.0


def test_read_trades_offset_beyond_end(tmp_path, monkeypatch):
    path = tmp_path / "trades.json"
    monkeypatch.setenv("TRADES_DB_PATH", str(path))
    trade_log.append_trade(**_sample_trade())
    assert trade_log.read_trades(limit=10, offset=100) == []


# ---------------------------------------------------------------------------
# GET /trades endpoint
# ---------------------------------------------------------------------------


def _auth_token(email: str = "trades_user@example.com", password: str = "testpass") -> str:
    client.post("/auth/register", json={"email": email, "password": password})
    resp = client.post("/auth/login", json={"email": email, "password": password})
    return resp.json()["access_token"]


def test_get_trades_requires_auth():
    resp = client.get("/trades")
    assert resp.status_code == 401


def test_get_trades_empty():
    token = _auth_token()
    resp = client.get("/trades", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["trades"] == []
    assert data["limit"] == 50
    assert data["offset"] == 0


def test_get_trades_returns_records():
    token = _auth_token("trades2@example.com")
    trade_log.append_trade(**_sample_trade(side="buy"))
    trade_log.append_trade(**_sample_trade(side="sell"))
    resp = client.get("/trades", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["trades"]) == 2
    # newest first
    assert data["trades"][0]["side"] == "sell"


def test_get_trades_pagination_params():
    token = _auth_token("trades3@example.com")
    for i in range(5):
        trade_log.append_trade(**_sample_trade(price=float(i)))
    resp = client.get(
        "/trades?limit=2&offset=1", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["limit"] == 2
    assert data["offset"] == 1
    assert len(data["trades"]) == 2
    # newest first: 4,3,2,1,0 → offset 1 gives 3,2
    assert data["trades"][0]["price"] == 3.0
