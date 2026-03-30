"""Tests for the subscription manager and upgrade endpoint."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from cashflow_engine.api.app import app
from cashflow_engine.config import SubscriptionConfig
from cashflow_engine.subscriptions.manager import StripeClient, SubscriptionManager

_client = TestClient(app)


def _register_and_login(email: str, tier: str = "free") -> str:
    _client.post("/auth/register", json={"email": email, "password": "testpass", "tier": tier})
    return _client.post("/auth/login", json={"email": email, "password": "testpass"}).json()["access_token"]


def test_add_subscriber(tmp_path, monkeypatch):
    monkeypatch.setenv("SUBSCRIPTIONS_DB_PATH", str(tmp_path / "subs.json"))
    mgr = SubscriptionManager(SubscriptionConfig(trial_days=7))
    record = mgr.add_subscriber("user-1")
    assert record["id"] == "user-1"
    assert record["trial_days_remaining"] == 7
    assert mgr.status()["subscriber_count"] == 1


def test_add_subscriber_includes_stripe_fields(tmp_path, monkeypatch):
    monkeypatch.setenv("SUBSCRIPTIONS_DB_PATH", str(tmp_path / "subs.json"))
    mgr = SubscriptionManager(SubscriptionConfig())
    record = mgr.add_subscriber("user-1")
    assert "stripe_customer_id" in record
    assert "stripe_subscription_id" in record
    assert record["stripe_customer_id"] is None
    assert record["stripe_subscription_id"] is None


def test_process_renewals_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("SUBSCRIPTIONS_DB_PATH", str(tmp_path / "subs.json"))
    mgr = SubscriptionManager(SubscriptionConfig())
    result = mgr.process_renewals()
    assert result == {"renewed": 0, "failed": 0, "total": 0}


def test_process_renewals_with_subscribers(tmp_path, monkeypatch):
    monkeypatch.setenv("SUBSCRIPTIONS_DB_PATH", str(tmp_path / "subs.json"))
    mgr = SubscriptionManager(SubscriptionConfig())
    mgr.add_subscriber("a")
    mgr.add_subscriber("b")
    result = mgr.process_renewals()
    assert result["total"] == 2


def test_process_renewals_no_stripe_returns_zeros(tmp_path, monkeypatch):
    monkeypatch.setenv("SUBSCRIPTIONS_DB_PATH", str(tmp_path / "subs.json"))
    mgr = SubscriptionManager(SubscriptionConfig(stripe_secret_key=None))
    mgr.add_subscriber("user-1")
    result = mgr.process_renewals()
    assert result == {"renewed": 0, "failed": 0, "total": 1}


@patch("cashflow_engine.subscriptions.manager.StripeClient")
def test_add_subscriber_creates_stripe_customer(mock_stripe_cls, tmp_path, monkeypatch):
    monkeypatch.setenv("SUBSCRIPTIONS_DB_PATH", str(tmp_path / "subs.json"))
    mock_stripe = MagicMock()
    mock_stripe.create_customer.return_value = "cus_test123"
    mock_stripe_cls.return_value = mock_stripe

    mgr = SubscriptionManager(SubscriptionConfig(stripe_secret_key="sk_test"))
    record = mgr.add_subscriber("user-1", email="user@example.com", name="Test User")

    mock_stripe.create_customer.assert_called_once_with("user@example.com", "Test User")
    assert record["stripe_customer_id"] == "cus_test123"


@patch("cashflow_engine.subscriptions.manager.StripeClient")
def test_add_subscriber_no_email_skips_stripe(mock_stripe_cls, tmp_path, monkeypatch):
    monkeypatch.setenv("SUBSCRIPTIONS_DB_PATH", str(tmp_path / "subs.json"))
    mock_stripe = MagicMock()
    mock_stripe_cls.return_value = mock_stripe

    mgr = SubscriptionManager(SubscriptionConfig(stripe_secret_key="sk_test"))
    record = mgr.add_subscriber("user-1")

    mock_stripe.create_customer.assert_not_called()
    assert record["stripe_customer_id"] is None


@patch("cashflow_engine.subscriptions.manager.StripeClient")
def test_process_renewals_active_subscription_counts_renewed(mock_stripe_cls, tmp_path, monkeypatch):
    monkeypatch.setenv("SUBSCRIPTIONS_DB_PATH", str(tmp_path / "subs.json"))
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
def test_process_renewals_trialing_subscription_counts_renewed(mock_stripe_cls, tmp_path, monkeypatch):
    monkeypatch.setenv("SUBSCRIPTIONS_DB_PATH", str(tmp_path / "subs.json"))
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
def test_process_renewals_past_due_subscription_counts_failed(mock_stripe_cls, tmp_path, monkeypatch):
    monkeypatch.setenv("SUBSCRIPTIONS_DB_PATH", str(tmp_path / "subs.json"))
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
def test_process_renewals_stripe_exception_counts_failed(mock_stripe_cls, tmp_path, monkeypatch):
    monkeypatch.setenv("SUBSCRIPTIONS_DB_PATH", str(tmp_path / "subs.json"))
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
def test_process_renewals_overdue_trial_creates_subscription(mock_stripe_cls, tmp_path, monkeypatch):
    monkeypatch.setenv("SUBSCRIPTIONS_DB_PATH", str(tmp_path / "subs.json"))
    mock_stripe = MagicMock()
    mock_stripe.create_customer.return_value = "cus_test123"
    mock_stripe.create_subscription.return_value = "sub_new123"
    mock_stripe_cls.return_value = mock_stripe

    mgr = SubscriptionManager(
        SubscriptionConfig(stripe_secret_key="sk_test", stripe_price_id_pro="price_pro")
    )
    subscriber = mgr.add_subscriber("user-1", email="user@example.com", name="Test")
    subscriber["trial_days_remaining"] = 1

    result = mgr.process_renewals()
    mock_stripe.create_subscription.assert_called_once_with("cus_test123", "price_pro")
    assert result["renewed"] == 1
    assert result["failed"] == 0
    assert subscriber["stripe_subscription_id"] == "sub_new123"


@patch("cashflow_engine.subscriptions.manager.StripeClient")
def test_process_renewals_overdue_trial_create_fails_counts_failed(mock_stripe_cls, tmp_path, monkeypatch):
    monkeypatch.setenv("SUBSCRIPTIONS_DB_PATH", str(tmp_path / "subs.json"))
    mock_stripe = MagicMock()
    mock_stripe.create_customer.return_value = "cus_test123"
    mock_stripe.create_subscription.side_effect = Exception("Card declined")
    mock_stripe_cls.return_value = mock_stripe

    mgr = SubscriptionManager(
        SubscriptionConfig(stripe_secret_key="sk_test", stripe_price_id_pro="price_pro")
    )
    subscriber = mgr.add_subscriber("user-1", email="user@example.com", name="Test")
    subscriber["trial_days_remaining"] = 1

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


@patch("cashflow_engine.subscriptions.manager.stripe")
def test_stripe_client_create_checkout_session(mock_stripe):
    mock_session = MagicMock()
    mock_session.url = "https://checkout.stripe.com/pay/cs_test_abc"
    mock_stripe.checkout.Session.create.return_value = mock_session

    client = StripeClient("sk_test")
    url = client.create_checkout_session(
        "cus_abc", "price_pro", "https://example.com/success", "https://example.com/cancel"
    )

    mock_stripe.checkout.Session.create.assert_called_once_with(
        customer="cus_abc",
        mode="subscription",
        line_items=[{"price": "price_pro", "quantity": 1}],
        success_url="https://example.com/success",
        cancel_url="https://example.com/cancel",
    )
    assert url == "https://checkout.stripe.com/pay/cs_test_abc"


# --- /subscriptions/upgrade endpoint tests ---


def test_upgrade_requires_auth():
    resp = _client.get("/subscriptions/upgrade")
    assert resp.status_code == 401


def test_upgrade_no_stripe_configured(monkeypatch):
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    token = _register_and_login("nostripe@test.com")
    resp = _client.get("/subscriptions/upgrade", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 503


@patch("cashflow_engine.subscriptions.router.StripeClient")
def test_upgrade_creates_customer_and_checkout_session(mock_stripe_cls, monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test")
    monkeypatch.setenv("STRIPE_PRICE_ID_PRO", "price_pro")
    monkeypatch.setenv("FRONTEND_URL", "https://app.example.com")

    mock_stripe = MagicMock()
    mock_stripe.create_customer.return_value = "cus_new"
    mock_stripe.create_checkout_session.return_value = "https://checkout.stripe.com/session123"
    mock_stripe_cls.return_value = mock_stripe

    token = _register_and_login("upgrade@test.com")
    resp = _client.get("/subscriptions/upgrade", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json() == {"checkout_url": "https://checkout.stripe.com/session123"}
    mock_stripe.create_customer.assert_called_once_with("upgrade@test.com", "upgrade@test.com")
    mock_stripe.create_checkout_session.assert_called_once_with(
        "cus_new",
        "price_pro",
        success_url="https://app.example.com/upgrade/success",
        cancel_url="https://app.example.com/upgrade/cancel",
    )


@patch("cashflow_engine.subscriptions.router.StripeClient")
def test_upgrade_reuses_existing_customer_id(mock_stripe_cls, monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test")
    monkeypatch.setenv("STRIPE_PRICE_ID_PRO", "price_pro")

    mock_stripe = MagicMock()
    mock_stripe.create_checkout_session.return_value = "https://checkout.stripe.com/reuse"
    mock_stripe_cls.return_value = mock_stripe

    # Pre-register with a known stripe_customer_id by calling upgrade twice
    token = _register_and_login("reuse@test.com")
    mock_stripe.create_customer.return_value = "cus_existing"

    # First call creates the customer
    _client.get("/subscriptions/upgrade", headers={"Authorization": f"Bearer {token}"})
    # Second call should reuse the stored customer_id
    resp = _client.get("/subscriptions/upgrade", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    # create_customer should only have been called once total
    assert mock_stripe.create_customer.call_count == 1


@patch("cashflow_engine.subscriptions.router.StripeClient")
def test_upgrade_no_price_id_returns_503(mock_stripe_cls, monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test")
    monkeypatch.delenv("STRIPE_PRICE_ID_PRO", raising=False)

    mock_stripe = MagicMock()
    mock_stripe.create_customer.return_value = "cus_noprice"
    mock_stripe_cls.return_value = mock_stripe

    token = _register_and_login("noprice@test.com")
    resp = _client.get("/subscriptions/upgrade", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 503
