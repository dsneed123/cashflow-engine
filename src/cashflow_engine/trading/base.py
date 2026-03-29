"""Trading module skeleton."""

from __future__ import annotations

import structlog

from cashflow_engine.config import TradingConfig

log = structlog.get_logger(__name__)


class TradingModule:
    def __init__(self, config: TradingConfig) -> None:
        self.config = config

    def status(self) -> dict:
        return {"enabled": self.config.enabled, "dry_run": self.config.dry_run}

    def run(self) -> dict:
        log.info("trading_run", dry_run=self.config.dry_run)
        # Placeholder: plug in exchange API client here
        return {"orders_placed": 0, "dry_run": self.config.dry_run}
