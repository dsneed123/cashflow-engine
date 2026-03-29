"""Tests for the subscription manager."""

from cashflow_engine.config import SubscriptionConfig
from cashflow_engine.subscriptions.manager import SubscriptionManager


def test_add_subscriber():
    mgr = SubscriptionManager(SubscriptionConfig(trial_days=7))
    record = mgr.add_subscriber("user-1")
    assert record["id"] == "user-1"
    assert record["trial_days_remaining"] == 7
    assert mgr.status()["subscriber_count"] == 1


def test_process_renewals_empty():
    mgr = SubscriptionManager(SubscriptionConfig())
    result = mgr.process_renewals()
    assert result == {"renewed": 0, "failed": 0, "total": 0}


def test_process_renewals_with_subscribers():
    mgr = SubscriptionManager(SubscriptionConfig())
    mgr.add_subscriber("a")
    mgr.add_subscriber("b")
    result = mgr.process_renewals()
    assert result["total"] == 2
