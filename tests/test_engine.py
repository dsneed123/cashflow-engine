"""Tests for the core engine."""

import pytest

from cashflow_engine.config import EngineConfig, TradingConfig, ArbitrageConfig, SubscriptionConfig
from cashflow_engine.core.engine import CashflowEngine


def test_engine_defaults():
    engine = CashflowEngine()
    status = engine.status()
    assert "trading" in status
    assert "arbitrage" in status
    assert "subscriptions" in status


def test_engine_run_cycle_no_modules_enabled():
    config = EngineConfig(
        trading=TradingConfig(enabled=False),
        arbitrage=ArbitrageConfig(enabled=False),
        subscriptions=SubscriptionConfig(enabled=False),
    )
    engine = CashflowEngine(config)
    result = engine.run_cycle()
    assert result == {}


def test_engine_run_cycle_subscriptions_only():
    config = EngineConfig(
        trading=TradingConfig(enabled=False),
        arbitrage=ArbitrageConfig(enabled=False),
        subscriptions=SubscriptionConfig(enabled=True),
    )
    engine = CashflowEngine(config)
    result = engine.run_cycle()
    assert "subscriptions" in result
    assert result["subscriptions"]["total"] == 0


def test_engine_run_cycle_all_modules():
    config = EngineConfig(
        trading=TradingConfig(enabled=True, dry_run=True),
        arbitrage=ArbitrageConfig(enabled=True, dry_run=True),
        subscriptions=SubscriptionConfig(enabled=True),
    )
    engine = CashflowEngine(config)
    result = engine.run_cycle()
    assert set(result.keys()) == {"trading", "arbitrage", "subscriptions"}
