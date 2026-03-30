"""Tests for the subscription manager."""

from unittest.mock import MagicMock, patch

from cashflow_engine.config import SubscriptionConfig
from cashflow_engine.subscriptions.manager import StripeClient, SubscriptionManager


def test_add_subscriber():
    mgr = SubscriptionManager(SubscriptionConfig(trial_days=7))
    record = mgr.add_subscriber("user-1")
    assert record["id"] == "user-1"
    assert record["trial_days_remaining"] == 7
    assert mgr.status()["subscriber_count"] == 1


def test_add_subscriber_includes_stripe_fields():
    mgr = SubscriptionManager(SubscriptionConfig())
    record = mgr.add_subscriber("user-1")
    assert "stripe_customer_id" in record
    assert "stripe_subscription_id" in record
    assert record["stripe_customer_id"] is None
    assert record["stripe_subscription_id"] is None


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


def test_process_renewals_no_stripe_returns_zeros():
    mgr = SubscriptionManager(SubscriptionConfig(stripe_secret_key=None))
    mgr.add_subscriber("user-1")
    result = mgr.process_renewals()
    assert result == {"renewed": 0, "failed": 0, "total": 1}


@patch("cashflow_engine.subscriptions.manager.StripeClient")
def test_add_subscriber_creates_stripe_customer(mock_stripe_cls):
    mock_stripe = MagicMock()
    mock_stripe.create_customer.return_value = "cus_test123"
    mock_stripe_cls.return_value = mock_stripe

    mgr = SubscriptionManager(SubscriptionConfig(stripe_secret_key="sk_test"))
    record = mgr.add_subscriber("user-1", email="user@example.com", name="Test User")

    mock_stripe.create_customer.assert_called_once_with("user@example.com", "Test User")
    assert record["stripe_customer_id"] == "cus_test123"


@patch("cashflow_engine.subscriptions.manager.StripeClient")
def test_add_subscriber_no_email_skips_stripe(mock_stripe_cls):
    mock_stripe = MagicMock()
    mock_stripe_cls.return_value = mock_stripe

    mgr = SubscriptionManager(SubscriptionConfig(stripe_secret_key="sk_test"))
    record = mgr.add_subscriber("user-1")

    mock_stripe.create_customer.assert_not_called()
    assert record["stripe_customer_id"] is None


@patch("cashflow_engine.subscriptions.manager.StripeClient")
def test_process_renewals_active_subscription_counts_renewed(mock_stripe_cls):
    mock_stripe = MagicMock()
    mock_stripe.get_subscription.return_value = {"status": "active"}
    mock_stripe_cls.return_value = mock_stripe

    mgr = SubscriptionManager(SubscriptionConfig(stripe_secret_key="sk_test"))
    subscriber = mgr.add_subscriber("user-1")
    subscriber["stripe_subscription_id"] = "sub_test123"

    result = mgr.process_renewals()
    mock_stripe.get_subscription.assert_called_once_with("sub_test123")
    assert result["renewed"] == 1
    assert result["failed"] == 0


@patch("cashflow_engine.subscriptions.manager.StripeClient")
def test_process_renewals_trialing_subscription_counts_renewed(mock_stripe_cls):
    mock_stripe = MagicMock()
    mock_stripe.get_subscription.return_value = {"status": "trialing"}
    mock_stripe_cls.return_value = mock_stripe

    mgr = SubscriptionManager(SubscriptionConfig(stripe_secret_key="sk_test"))
    subscriber = mgr.add_subscriber("user-1")
    subscriber["stripe_subscription_id"] = "sub_test123"

    result = mgr.process_renewals()
    assert result["renewed"] == 1
    assert result["failed"] == 0


@patch("cashflow_engine.subscriptions.manager.StripeClient")
def test_process_renewals_past_due_subscription_counts_failed(mock_stripe_cls):
    mock_stripe = MagicMock()
    mock_stripe.get_subscription.return_value = {"status": "past_due"}
    mock_stripe_cls.return_value = mock_stripe

    mgr = SubscriptionManager(SubscriptionConfig(stripe_secret_key="sk_test"))
    subscriber = mgr.add_subscriber("user-1")
    subscriber["stripe_subscription_id"] = "sub_test123"

    result = mgr.process_renewals()
    assert result["renewed"] == 0
    assert result["failed"] == 1


@patch("cashflow_engine.subscriptions.manager.StripeClient")
def test_process_renewals_stripe_exception_counts_failed(mock_stripe_cls):
    mock_stripe = MagicMock()
    mock_stripe.get_subscription.side_effect = Exception("Network error")
    mock_stripe_cls.return_value = mock_stripe

    mgr = SubscriptionManager(SubscriptionConfig(stripe_secret_key="sk_test"))
    subscriber = mgr.add_subscriber("user-1")
    subscriber["stripe_subscription_id"] = "sub_test123"

    result = mgr.process_renewals()
    assert result["renewed"] == 0
    assert result["failed"] == 1


@patch("cashflow_engine.subscriptions.manager.StripeClient")
def test_process_renewals_overdue_trial_creates_subscription(mock_stripe_cls):
    mock_stripe = MagicMock()
    mock_stripe.create_customer.return_value = "cus_test123"
    mock_stripe.create_subscription.return_value = "sub_new123"
    mock_stripe_cls.return_value = mock_stripe

    mgr = SubscriptionManager(
        SubscriptionConfig(stripe_secret_key="sk_test", stripe_price_id_pro="price_pro")
    )
    subscriber = mgr.add_subscriber("user-1", email="user@example.com", name="Test")
    subscriber["trial_days_remaining"] = 0

    result = mgr.process_renewals()
    mock_stripe.create_subscription.assert_called_once_with("cus_test123", "price_pro")
    assert result["renewed"] == 1
    assert result["failed"] == 0
    assert subscriber["stripe_subscription_id"] == "sub_new123"


@patch("cashflow_engine.subscriptions.manager.StripeClient")
def test_process_renewals_overdue_trial_create_fails_counts_failed(mock_stripe_cls):
    mock_stripe = MagicMock()
    mock_stripe.create_customer.return_value = "cus_test123"
    mock_stripe.create_subscription.side_effect = Exception("Card declined")
    mock_stripe_cls.return_value = mock_stripe

    mgr = SubscriptionManager(
        SubscriptionConfig(stripe_secret_key="sk_test", stripe_price_id_pro="price_pro")
    )
    subscriber = mgr.add_subscriber("user-1", email="user@example.com", name="Test")
    subscriber["trial_days_remaining"] = 0

    result = mgr.process_renewals()
    assert result["renewed"] == 0
    assert result["failed"] == 1


@patch("cashflow_engine.subscriptions.manager.stripe")
def test_stripe_client_create_customer(mock_stripe):
    mock_stripe.Customer.create.return_value = MagicMock(id="cus_abc")
    client = StripeClient("sk_test")
    customer_id = client.create_customer("test@example.com", "Test User")
    mock_stripe.Customer.create.assert_called_once_with(email="test@example.com", name="Test User")
    assert customer_id == "cus_abc"


@patch("cashflow_engine.subscriptions.manager.stripe")
def test_stripe_client_create_subscription(mock_stripe):
    mock_stripe.Subscription.create.return_value = MagicMock(id="sub_abc")
    client = StripeClient("sk_test")
    sub_id = client.create_subscription("cus_abc", "price_pro")
    mock_stripe.Subscription.create.assert_called_once_with(
        customer="cus_abc", items=[{"price": "price_pro"}]
    )
    assert sub_id == "sub_abc"


@patch("cashflow_engine.subscriptions.manager.stripe")
def test_stripe_client_cancel_subscription(mock_stripe):
    client = StripeClient("sk_test")
    client.cancel_subscription("sub_abc")
    mock_stripe.Subscription.cancel.assert_called_once_with("sub_abc")


@patch("cashflow_engine.subscriptions.manager.stripe")
def test_stripe_client_get_subscription(mock_stripe):
    mock_stripe.Subscription.retrieve.return_value = {"id": "sub_abc", "status": "active"}
    client = StripeClient("sk_test")
    result = client.get_subscription("sub_abc")
    mock_stripe.Subscription.retrieve.assert_called_once_with("sub_abc")
    assert result["status"] == "active"
