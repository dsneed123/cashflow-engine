"""Tests for the trading module."""

from cashflow_engine.config import TradingConfig
from cashflow_engine.trading.base import TradingModule


def test_trading_status():
    mod = TradingModule(TradingConfig(enabled=True, dry_run=True))
    assert mod.status() == {"enabled": True, "dry_run": True}


def test_trading_run_dry():
    mod = TradingModule(TradingConfig(enabled=True, dry_run=True))
    result = mod.run()
    assert result["dry_run"] is True
    assert result["orders_placed"] == 0
