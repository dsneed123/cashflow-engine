"""Tests for the trade log module."""

from __future__ import annotations

import concurrent.futures
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


# ---------------------------------------------------------------------------
# calculate_pnl
# ---------------------------------------------------------------------------


def test_calculate_pnl_empty_log():
    result = trade_log.calculate_pnl()
    assert result["realized_pnl"] == 0.0
    assert result["unrealized_value"] == 0.0
    assert result["trade_count"] == 0
    assert result["dry_run_count"] == 0
    assert result["wins"] == 0
    assert result["losses"] == 0
    assert result["win_loss_ratio"] is None
    assert result["symbols"] == {}


def test_calculate_pnl_all_buys_unrealized():
    trade_log.append_trade(**_sample_trade(side="buy", price=50000.0, amount=0.1, dry_run=False))
    trade_log.append_trade(**_sample_trade(side="buy", price=48000.0, amount=0.2, dry_run=False))
    result = trade_log.calculate_pnl()
    assert result["realized_pnl"] == 0.0
    # unrealized_value = cost basis: 0.1*50000 + 0.2*48000 = 14600
    assert result["unrealized_value"] == pytest.approx(14600.0)
    assert result["trade_count"] == 2
    assert result["wins"] == 0
    assert result["losses"] == 0
    assert result["win_loss_ratio"] is None


def test_calculate_pnl_matched_pair_profit():
    trade_log.append_trade(**_sample_trade(side="buy", price=45000.0, amount=0.1, dry_run=False))
    trade_log.append_trade(**_sample_trade(side="sell", price=50000.0, amount=0.1, dry_run=False))
    result = trade_log.calculate_pnl()
    # realized P&L = (50000 - 45000) * 0.1 = 500
    assert result["realized_pnl"] == pytest.approx(500.0)
    assert result["unrealized_value"] == pytest.approx(0.0)
    assert result["trade_count"] == 2
    assert result["wins"] == 1
    assert result["losses"] == 0
    assert result["win_loss_ratio"] is None  # no losses to divide by


def test_calculate_pnl_matched_pair_loss():
    trade_log.append_trade(**_sample_trade(side="buy", price=50000.0, amount=0.1, dry_run=False))
    trade_log.append_trade(**_sample_trade(side="sell", price=45000.0, amount=0.1, dry_run=False))
    result = trade_log.calculate_pnl()
    # realized P&L = (45000 - 50000) * 0.1 = -500
    assert result["realized_pnl"] == pytest.approx(-500.0)
    assert result["wins"] == 0
    assert result["losses"] == 1
    assert result["win_loss_ratio"] == pytest.approx(0.0)  # 0 wins / 1 loss


def test_calculate_pnl_multiple_symbols():
    trade_log.append_trade(**_sample_trade(symbol="BTC/USDT", side="buy", price=45000.0, amount=0.1, dry_run=False))
    trade_log.append_trade(**_sample_trade(symbol="ETH/USDT", side="buy", price=3000.0, amount=1.0, dry_run=False))
    trade_log.append_trade(**_sample_trade(symbol="BTC/USDT", side="sell", price=50000.0, amount=0.1, dry_run=False))
    result = trade_log.calculate_pnl()
    assert result["realized_pnl"] == pytest.approx(500.0)
    # ETH/USDT still open: cost basis 3000
    assert result["unrealized_value"] == pytest.approx(3000.0)
    assert "BTC/USDT" in result["symbols"]
    assert "ETH/USDT" in result["symbols"]
    assert result["symbols"]["BTC/USDT"]["realized_pnl"] == pytest.approx(500.0)
    assert result["symbols"]["ETH/USDT"]["unrealized_value"] == pytest.approx(3000.0)


def test_calculate_pnl_dry_run_excluded():
    trade_log.append_trade(**_sample_trade(side="buy", price=45000.0, amount=0.1, dry_run=True))
    trade_log.append_trade(**_sample_trade(side="sell", price=50000.0, amount=0.1, dry_run=True))
    result = trade_log.calculate_pnl()
    assert result["realized_pnl"] == 0.0
    assert result["unrealized_value"] == 0.0
    assert result["trade_count"] == 0
    assert result["dry_run_count"] == 2


def test_calculate_pnl_symbol_filter():
    trade_log.append_trade(**_sample_trade(symbol="BTC/USDT", side="buy", price=45000.0, amount=0.1, dry_run=False))
    trade_log.append_trade(**_sample_trade(symbol="ETH/USDT", side="buy", price=3000.0, amount=1.0, dry_run=False))
    trade_log.append_trade(**_sample_trade(symbol="BTC/USDT", side="sell", price=50000.0, amount=0.1, dry_run=False))
    result = trade_log.calculate_pnl(symbol="BTC/USDT")
    assert result["realized_pnl"] == pytest.approx(500.0)
    assert result["trade_count"] == 2
    assert "symbols" not in result  # no breakdown when filtering by symbol


def test_calculate_pnl_fifo_partial_lots():
    # Buy 0.3 BTC, sell 0.1 twice — FIFO should consume from first lot
    trade_log.append_trade(**_sample_trade(side="buy", price=40000.0, amount=0.3, dry_run=False))
    trade_log.append_trade(**_sample_trade(side="sell", price=50000.0, amount=0.1, dry_run=False))
    trade_log.append_trade(**_sample_trade(side="sell", price=50000.0, amount=0.1, dry_run=False))
    result = trade_log.calculate_pnl()
    # Each sell: (50000 - 40000) * 0.1 = 1000; total = 2000
    assert result["realized_pnl"] == pytest.approx(2000.0)
    # Remaining: 0.1 BTC at 40000 = 4000
    assert result["unrealized_value"] == pytest.approx(4000.0)


# ---------------------------------------------------------------------------
# GET /pnl and GET /pnl/{symbol} endpoints
# ---------------------------------------------------------------------------


def test_get_pnl_requires_auth():
    resp = client.get("/pnl")
    assert resp.status_code == 401


def test_get_pnl_empty():
    token = _auth_token("pnl_user@example.com")
    resp = client.get("/pnl", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["realized_pnl"] == 0.0
    assert data["trade_count"] == 0
    assert data["symbols"] == {}


def test_get_pnl_with_trades():
    token = _auth_token("pnl2@example.com")
    trade_log.append_trade(**_sample_trade(side="buy", price=45000.0, amount=0.1, dry_run=False))
    trade_log.append_trade(**_sample_trade(side="sell", price=50000.0, amount=0.1, dry_run=False))
    resp = client.get("/pnl", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["realized_pnl"] == pytest.approx(500.0)
    assert data["wins"] == 1


def test_get_pnl_symbol_requires_auth():
    resp = client.get("/pnl/BTC/USDT")
    assert resp.status_code == 401


def test_get_pnl_symbol():
    token = _auth_token("pnl3@example.com")
    trade_log.append_trade(**_sample_trade(symbol="BTC/USDT", side="buy", price=45000.0, amount=0.1, dry_run=False))
    trade_log.append_trade(**_sample_trade(symbol="ETH/USDT", side="buy", price=3000.0, amount=1.0, dry_run=False))
    trade_log.append_trade(**_sample_trade(symbol="BTC/USDT", side="sell", price=50000.0, amount=0.1, dry_run=False))
    resp = client.get("/pnl/BTC/USDT", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["realized_pnl"] == pytest.approx(500.0)
    assert data["trade_count"] == 2
    assert "symbols" not in data


# ---------------------------------------------------------------------------
# Concurrent-write stress tests
# ---------------------------------------------------------------------------


def test_append_trade_concurrent_no_lost_writes(tmp_path, monkeypatch):
    """Concurrent appends must not lose any records."""
    path = tmp_path / "trades.json"
    monkeypatch.setenv("TRADES_DB_PATH", str(path))
    n = 20
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [
            executor.submit(trade_log.append_trade, **_sample_trade(price=float(i)))
            for i in range(n)
        ]
        for f in concurrent.futures.as_completed(futures):
            f.result()
    with path.open() as f:
        records = json.load(f)
    assert len(records) == n
