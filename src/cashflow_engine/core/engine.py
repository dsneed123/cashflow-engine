"""Central orchestration engine."""

from __future__ import annotations

import structlog

from cashflow_engine.config import EngineConfig
from cashflow_engine.trading.base import TradingModule
from cashflow_engine.arbitrage.detector import ArbitrageDetector
from cashflow_engine.subscriptions.manager import SubscriptionManager

log = structlog.get_logger(__name__)


class CashflowEngine:
    """Top-level coordinator for all revenue modules."""

    def __init__(self, config: EngineConfig | None = None) -> None:
        self.config = config or EngineConfig()
        self.trading = TradingModule(self.config.trading)
        self.arbitrage = ArbitrageDetector(self.config.arbitrage)
        self.subscriptions = SubscriptionManager(self.config.subscriptions)

    def status(self) -> dict:
        return {
            "trading": self.trading.status(),
            "arbitrage": self.arbitrage.status(),
            "subscriptions": self.subscriptions.status(),
        }

    def run_cycle(self) -> dict[str, object]:
        """Execute one revenue cycle across all enabled modules."""
        results: dict[str, object] = {}

        if self.config.trading.enabled:
            results["trading"] = self.trading.run()
        if self.config.arbitrage.enabled:
            results["arbitrage"] = self.arbitrage.scan()
        if self.config.subscriptions.enabled:
            results["subscriptions"] = self.subscriptions.process_renewals()

        log.info("cycle_complete", modules_run=list(results.keys()))
        return results
