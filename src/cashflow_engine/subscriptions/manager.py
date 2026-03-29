"""Subscription lifecycle manager skeleton."""

from __future__ import annotations

import structlog

from cashflow_engine.config import SubscriptionConfig

log = structlog.get_logger(__name__)


class SubscriptionManager:
    def __init__(self, config: SubscriptionConfig) -> None:
        self.config = config
        self._subscribers: list[dict] = []

    def status(self) -> dict:
        return {"enabled": self.config.enabled, "subscriber_count": len(self._subscribers)}

    def add_subscriber(self, subscriber_id: str) -> dict:
        record = {"id": subscriber_id, "trial_days_remaining": self.config.trial_days}
        self._subscribers.append(record)
        log.info("subscriber_added", subscriber_id=subscriber_id)
        return record

    def process_renewals(self) -> dict:
        log.info("processing_renewals", count=len(self._subscribers))
        # Placeholder: integrate with payment provider here
        return {"renewed": 0, "failed": 0, "total": len(self._subscribers)}
