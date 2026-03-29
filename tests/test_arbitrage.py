"""Tests for the arbitrage detector."""

from cashflow_engine.config import ArbitrageConfig
from cashflow_engine.arbitrage.detector import ArbitrageDetector


def test_arbitrage_status():
    det = ArbitrageDetector(ArbitrageConfig(min_spread_pct=1.0))
    assert det.status()["min_spread_pct"] == 1.0


def test_arbitrage_scan_returns_dict():
    det = ArbitrageDetector(ArbitrageConfig(enabled=True, dry_run=True))
    result = det.scan()
    assert "opportunities_found" in result
    assert result["dry_run"] is True
