"""Arbitrage opportunity detector skeleton."""

from __future__ import annotations

import structlog

from cashflow_engine.config import ArbitrageConfig
from cashflow_engine.core.trade_log import append_trade

log = structlog.get_logger(__name__)


class ArbitrageDetector:
    def __init__(self, config: ArbitrageConfig) -> None:
        self.config = config

    def status(self) -> dict:
        return {"enabled": self.config.enabled, "min_spread_pct": self.config.min_spread_pct}

    def scan(self) -> dict:
        log.info("arbitrage_scan", min_spread_pct=self.config.min_spread_pct)
        # Placeholder: compare prices across venues here
        opportunities: list[dict] = []
        for opp in opportunities:
            append_trade(
                module="arbitrage",
                symbol=opp["symbol"],
                side=opp["side"],
                amount=opp["amount"],
                price=opp["price"],
                exchange=opp["exchange"],
                dry_run=self.config.dry_run,
                order_id=opp.get("order_id"),
            )
        return {"opportunities_found": len(opportunities), "dry_run": self.config.dry_run}
