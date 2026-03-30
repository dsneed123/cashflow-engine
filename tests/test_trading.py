"""Tests for the trading module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from cashflow_engine.config import TradingConfig
from cashflow_engine.trading.base import ExchangeClient, TradingModule


def _mock_exchange(price: float = 50000.0, ma_price: float = 49000.0) -> MagicMock:
    """Build a mock ccxt exchange. Default: price > MA → buy signal."""
    exchange = MagicMock()
    exchange.fetch_ticker.return_value = {"last": price, "symbol": "BTC/USDT"}
    # OHLCV candle format: [timestamp, open, high, low, close, volume]
    exchange.fetch_ohlcv.return_value = [
        [0, ma_price, ma_price, ma_price, ma_price, 1.0] for _ in range(24)
    ]
    exchange.create_market_order.return_value = {
        "id": "order-123",
        "symbol": "BTC/USDT",
        "side": "buy",
        "amount": 0.02,
        "price": price,
        "status": "closed",
    }
    return exchange


@pytest.fixture
def binance_mock():
    exchange = _mock_exchange()
    with patch("ccxt.binance", return_value=exchange):
        yield exchange


def test_trading_status(binance_mock):
    mod = TradingModule(TradingConfig(enabled=True, dry_run=True))
    assert mod.status() == {"enabled": True, "dry_run": True}


def test_trading_run_dry(binance_mock):
    mod = TradingModule(TradingConfig(enabled=True, dry_run=True))
    result = mod.run()
    assert result["dry_run"] is True
    assert result["orders_placed"] == 1
    assert result["signal"] in ("buy", "sell")
    # Dry run: real order not placed on exchange
    binance_mock.create_market_order.assert_not_called()


def test_trading_run_buy_signal(binance_mock):
    binance_mock.fetch_ticker.return_value = {"last": 55000.0, "symbol": "BTC/USDT"}
    binance_mock.fetch_ohlcv.return_value = [
        [0, 50000, 50000, 50000, 50000, 1.0] for _ in range(24)
    ]
    mod = TradingModule(TradingConfig(enabled=True, dry_run=True))
    result = mod.run()
    assert result["signal"] == "buy"
    assert result["price"] == 55000.0


def test_trading_run_sell_signal(binance_mock):
    binance_mock.fetch_ticker.return_value = {"last": 45000.0, "symbol": "BTC/USDT"}
    binance_mock.fetch_ohlcv.return_value = [
        [0, 50000, 50000, 50000, 50000, 1.0] for _ in range(24)
    ]
    mod = TradingModule(TradingConfig(enabled=True, dry_run=True))
    result = mod.run()
    assert result["signal"] == "sell"
    assert result["price"] == 45000.0


def test_trading_run_error_handling(binance_mock):
    binance_mock.fetch_ticker.side_effect = Exception("Network error")
    mod = TradingModule(TradingConfig(enabled=True, dry_run=True))
    result = mod.run()
    assert result["orders_placed"] == 0
    assert "error" in result
    assert result["dry_run"] is True


def test_exchange_client_fetch_ticker(binance_mock):
    client = ExchangeClient(TradingConfig())
    ticker = client.fetch_ticker("BTC/USDT")
    assert ticker["last"] == 50000.0
    binance_mock.fetch_ticker.assert_called_once_with("BTC/USDT")


def test_exchange_client_place_order_dry_run(binance_mock):
    client = ExchangeClient(TradingConfig(dry_run=True))
    order = client.place_order("BTC/USDT", "buy", 0.02)
    assert order["status"] == "simulated"
    assert order["side"] == "buy"
    assert order["price"] == 50000.0
    binance_mock.create_market_order.assert_not_called()


def test_exchange_client_place_order_live(binance_mock):
    client = ExchangeClient(TradingConfig(dry_run=False))
    client.place_order("BTC/USDT", "buy", 0.02)
    binance_mock.create_market_order.assert_called_once_with("BTC/USDT", "buy", 0.02)


def test_exchange_client_get_positions_dry_run(binance_mock):
    client = ExchangeClient(TradingConfig(dry_run=True))
    positions = client.get_positions()
    assert positions == []
    binance_mock.fetch_positions.assert_not_called()


def test_exchange_client_get_positions_live(binance_mock):
    mock_positions = [{"symbol": "BTC/USDT", "side": "long", "amount": 0.01}]
    binance_mock.fetch_positions.return_value = mock_positions
    client = ExchangeClient(TradingConfig(dry_run=False))
    positions = client.get_positions()
    assert positions == mock_positions


def test_trading_config_exchange_fields():
    config = TradingConfig(
        exchange_id="coinbase",
        api_key="test-key",
        api_secret="test-secret",
    )
    assert config.exchange_id == "coinbase"
    assert config.api_key == "test-key"
    assert config.api_secret == "test-secret"
