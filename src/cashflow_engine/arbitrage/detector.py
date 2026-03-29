"""Arbitrage opportunity detector skeleton."""

from __future__ import annotations

import structlog

from cashflow_engine.config import ArbitrageConfig

log = structlog.get_logger(__name__)


class ArbitrageDetector:
    def __init__(self, config: ArbitrageConfig) -> None:
        self.config = config

    def status(self) -> dict:
        return {"enabled": self.config.enabled, "min_spread_pct": self.config.min_spread_pct}

    def scan(self) -> dict:
        log.info("arbitrage_scan", min_spread_pct=self.config.min_spread_pct)
        # Placeholder: compare prices across venues here
        return {"opportunities_found": 0, "dry_run": self.config.dry_run}
