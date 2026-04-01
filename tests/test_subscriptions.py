"""Tests for the subscription manager and upgrade endpoint."""

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from cashflow_engine.api.app import app
from cashflow_engine.auth import store as auth_store
from cashflow_engine.auth.models import User
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


# --- SubscriptionManager.create_checkout_session tests ---


def test_create_checkout_session_no_stripe(tmp_path, monkeypatch):
    monkeypatch.setenv("SUBSCRIPTIONS_DB_PATH", str(tmp_path / "subs.json"))
    mgr = SubscriptionManager(SubscriptionConfig(stripe_secret_key=None))
    with pytest.raises(ValueError, match="Stripe not configured"):
        mgr.create_checkout_session("user-1", "price_pro")


@patch("cashflow_engine.subscriptions.manager.StripeClient")
def test_create_checkout_session_subscriber_not_found(mock_stripe_cls, tmp_path, monkeypatch):
    monkeypatch.setenv("SUBSCRIPTIONS_DB_PATH", str(tmp_path / "subs.json"))
    mock_stripe_cls.return_value = MagicMock()
    mgr = SubscriptionManager(SubscriptionConfig(stripe_secret_key="sk_test"))
    with pytest.raises(ValueError, match="not found"):
        mgr.create_checkout_session("nonexistent", "price_pro")


@patch("cashflow_engine.subscriptions.manager.StripeClient")
def test_create_checkout_session_no_customer_id(mock_stripe_cls, tmp_path, monkeypatch):
    monkeypatch.setenv("SUBSCRIPTIONS_DB_PATH", str(tmp_path / "subs.json"))
    mock_stripe_cls.return_value = MagicMock()
    mgr = SubscriptionManager(SubscriptionConfig(stripe_secret_key="sk_test"))
    mgr.add_subscriber("user-1")  # no email → stripe_customer_id stays None
    with pytest.raises(ValueError, match="no Stripe customer"):
        mgr.create_checkout_session("user-1", "price_pro")


@patch("cashflow_engine.subscriptions.manager.StripeClient")
def test_create_checkout_session_returns_url(mock_stripe_cls, tmp_path, monkeypatch):
    monkeypatch.setenv("SUBSCRIPTIONS_DB_PATH", str(tmp_path / "subs.json"))
    monkeypatch.setenv("FRONTEND_URL", "https://app.example.com")

    mock_stripe = MagicMock()
    mock_stripe.create_customer.return_value = "cus_test123"
    mock_stripe.create_checkout_session.return_value = "https://checkout.stripe.com/pay/cs_test"
    mock_stripe_cls.return_value = mock_stripe

    mgr = SubscriptionManager(SubscriptionConfig(stripe_secret_key="sk_test"))
    subscriber = mgr.add_subscriber("user-1", email="user@example.com", name="Test")

    url = mgr.create_checkout_session("user-1", "price_pro")

    mock_stripe.create_checkout_session.assert_called_once_with(
        "cus_test123",
        "price_pro",
        success_url="https://app.example.com/billing/success",
        cancel_url="https://app.example.com/billing/cancel",
    )
    assert url == "https://checkout.stripe.com/pay/cs_test"


# --- SubscriptionManager.handle_webhook tests ---


def test_handle_webhook_checkout_session_completed(tmp_path, monkeypatch):
    monkeypatch.setenv("SUBSCRIPTIONS_DB_PATH", str(tmp_path / "subs.json"))
    event = {
        "type": "checkout.session.completed",
        "data": {"object": {"customer": "cus_test123", "subscription": "sub_new123"}},
    }

    mgr = SubscriptionManager(SubscriptionConfig())
    mgr._subscribers.append({
        "id": "user-1",
        "trial_days_remaining": 7,
        "stripe_customer_id": "cus_test123",
        "stripe_subscription_id": None,
    })

    result = mgr.handle_webhook(event)

    assert result == {"status": "handled", "event_type": "checkout.session.completed"}
    assert mgr._subscribers[0]["stripe_subscription_id"] == "sub_new123"


def test_handle_webhook_subscription_deleted(tmp_path, monkeypatch):
    monkeypatch.setenv("SUBSCRIPTIONS_DB_PATH", str(tmp_path / "subs.json"))
    event = {
        "type": "customer.subscription.deleted",
        "data": {"object": {"id": "sub_test123", "customer": "cus_test123"}},
    }

    mgr = SubscriptionManager(SubscriptionConfig())
    mgr._subscribers.append({
        "id": "user-1",
        "trial_days_remaining": 0,
        "stripe_customer_id": "cus_test123",
        "stripe_subscription_id": "sub_test123",
    })

    result = mgr.handle_webhook(event)

    assert result == {"status": "handled", "event_type": "customer.subscription.deleted"}
    assert mgr._subscribers[0]["stripe_subscription_id"] is None


def test_handle_webhook_unknown_event_ignored(tmp_path, monkeypatch):
    monkeypatch.setenv("SUBSCRIPTIONS_DB_PATH", str(tmp_path / "subs.json"))
    event = {
        "type": "payment_intent.created",
        "data": {"object": {}},
    }

    mgr = SubscriptionManager(SubscriptionConfig())
    result = mgr.handle_webhook(event)

    assert result["status"] == "handled"
    assert result["event_type"] == "payment_intent.created"


# --- POST /billing/checkout endpoint tests ---


def test_billing_checkout_requires_auth():
    resp = _client.post("/billing/checkout", json={"price_id": "price_pro"})
    assert resp.status_code == 401


@patch("cashflow_engine.api.app._engine")
def test_billing_checkout_no_stripe_configured(mock_engine):
    mock_engine.subscriptions._stripe = None
    mock_engine.subscriptions._subscribers = []

    token = _register_and_login("ckout_ns@test.com")
    resp = _client.post(
        "/billing/checkout",
        json={"price_id": "price_pro"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 503


@patch("cashflow_engine.api.app._engine")
def test_billing_checkout_returns_checkout_url(mock_engine):
    mock_stripe = MagicMock()
    mock_engine.subscriptions._stripe = mock_stripe
    mock_engine.subscriptions._subscribers = []
    mock_engine.subscriptions.add_subscriber.return_value = {
        "id": "user-id",
        "stripe_customer_id": "cus_test",
        "trial_days_remaining": 14,
        "stripe_subscription_id": None,
    }
    mock_engine.subscriptions.create_checkout_session.return_value = "https://checkout.stripe.com/pay/x"

    token = _register_and_login("ckout_ok@test.com")
    resp = _client.post(
        "/billing/checkout",
        json={"price_id": "price_pro"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["checkout_url"] == "https://checkout.stripe.com/pay/x"
    mock_engine.subscriptions.create_checkout_session.assert_called_once()


# --- POST /billing/webhook endpoint tests ---


def test_billing_webhook_missing_signature():
    resp = _client.post("/billing/webhook", content=b"{}")
    assert resp.status_code == 400
    assert "Stripe-Signature" in resp.json()["detail"]


@patch("cashflow_engine.api.app.stripe")
@patch("cashflow_engine.api.app._engine")
def test_billing_webhook_invalid_signature(mock_engine, mock_stripe):
    mock_engine.subscriptions.config.stripe_webhook_secret = "whsec_test"
    mock_stripe.Webhook.construct_event.side_effect = Exception("No signatures found")
    resp = _client.post(
        "/billing/webhook",
        content=b"{}",
        headers={"Stripe-Signature": "invalid"},
    )
    assert resp.status_code == 400
    assert "signature" in resp.json()["detail"].lower()


@patch("cashflow_engine.api.app.stripe")
@patch("cashflow_engine.api.app._engine")
def test_billing_webhook_checkout_completed(mock_engine, mock_stripe):
    event_dict = {
        "type": "checkout.session.completed",
        "data": {"object": {"customer": "cus_test", "subscription": "sub_test"}},
    }
    mock_engine.subscriptions.config.stripe_webhook_secret = "whsec_test"
    mock_stripe.Webhook.construct_event.return_value = event_dict
    mock_engine.subscriptions.handle_webhook.return_value = {
        "status": "handled",
        "event_type": "checkout.session.completed",
    }
    payload = b'{"type": "checkout.session.completed"}'
    resp = _client.post(
        "/billing/webhook",
        content=payload,
        headers={"Stripe-Signature": "t=123,v1=abc"},
    )
    assert resp.status_code == 200
    assert resp.json()["event_type"] == "checkout.session.completed"
    mock_stripe.Webhook.construct_event.assert_called_once_with(payload, "t=123,v1=abc", "whsec_test")
    mock_engine.subscriptions.handle_webhook.assert_called_once_with(event_dict)


@patch("cashflow_engine.api.app.stripe")
@patch("cashflow_engine.api.app._engine")
def test_billing_webhook_subscription_deleted(mock_engine, mock_stripe):
    event_dict = {
        "type": "customer.subscription.deleted",
        "data": {"object": {"id": "sub_test"}},
    }
    mock_engine.subscriptions.config.stripe_webhook_secret = "whsec_test"
    mock_stripe.Webhook.construct_event.return_value = event_dict
    mock_engine.subscriptions.handle_webhook.return_value = {
        "status": "handled",
        "event_type": "customer.subscription.deleted",
    }
    resp = _client.post(
        "/billing/webhook",
        content=b'{"type": "customer.subscription.deleted"}',
        headers={"Stripe-Signature": "t=123,v1=abc"},
    )
    assert resp.status_code == 200
    assert resp.json()["event_type"] == "customer.subscription.deleted"


# --- Tier update on webhook tests ---


def _make_user(tmp_path, email: str, tier: str = "free", stripe_customer_id: str | None = None) -> User:
    user = User(
        id=str(uuid.uuid4()),
        email=email,
        hashed_password="hashed",
        tier=tier,
        created_at=datetime.now(timezone.utc),
        stripe_customer_id=stripe_customer_id,
    )
    auth_store.create_user(user)
    return user


def test_handle_webhook_checkout_completed_upgrades_user_tier(tmp_path, monkeypatch):
    monkeypatch.setenv("SUBSCRIPTIONS_DB_PATH", str(tmp_path / "subs.json"))
    monkeypatch.setenv("USERS_DB_PATH", str(tmp_path / "users.json"))

    user = _make_user(tmp_path, "checkout@example.com", tier="free", stripe_customer_id="cus_checkout1")

    event = {
        "type": "checkout.session.completed",
        "data": {"object": {"customer": "cus_checkout1", "subscription": "sub_new1"}},
    }

    mgr = SubscriptionManager(SubscriptionConfig())
    mgr._subscribers.append({
        "id": user.id,
        "trial_days_remaining": 7,
        "stripe_customer_id": "cus_checkout1",
        "stripe_subscription_id": None,
    })

    result = mgr.handle_webhook(event)

    assert result == {"status": "handled", "event_type": "checkout.session.completed"}
    assert mgr._subscribers[0]["stripe_subscription_id"] == "sub_new1"
    updated = auth_store.get_user_by_email("checkout@example.com")
    assert updated.tier == "pro"


def test_handle_webhook_subscription_deleted_downgrades_user_tier(tmp_path, monkeypatch):
    monkeypatch.setenv("SUBSCRIPTIONS_DB_PATH", str(tmp_path / "subs.json"))
    monkeypatch.setenv("USERS_DB_PATH", str(tmp_path / "users.json"))

    user = _make_user(tmp_path, "prouser@example.com", tier="pro", stripe_customer_id="cus_pro1")

    event = {
        "type": "customer.subscription.deleted",
        "data": {"object": {"id": "sub_pro1", "customer": "cus_pro1"}},
    }

    mgr = SubscriptionManager(SubscriptionConfig())
    mgr._subscribers.append({
        "id": user.id,
        "trial_days_remaining": 0,
        "stripe_customer_id": "cus_pro1",
        "stripe_subscription_id": "sub_pro1",
    })

    result = mgr.handle_webhook(event)

    assert result == {"status": "handled", "event_type": "customer.subscription.deleted"}
    assert mgr._subscribers[0]["stripe_subscription_id"] is None
    updated = auth_store.get_user_by_email("prouser@example.com")
    assert updated.tier == "free"


def test_handle_webhook_checkout_completed_no_matching_user_is_noop(tmp_path, monkeypatch):
    """Webhook should not fail if no user with that stripe_customer_id exists."""
    monkeypatch.setenv("SUBSCRIPTIONS_DB_PATH", str(tmp_path / "subs.json"))
    monkeypatch.setenv("USERS_DB_PATH", str(tmp_path / "users.json"))

    event = {
        "type": "checkout.session.completed",
        "data": {"object": {"customer": "cus_unknown", "subscription": "sub_x"}},
    }

    mgr = SubscriptionManager(SubscriptionConfig())
    result = mgr.handle_webhook(event)

    assert result["status"] == "handled"


def test_handle_webhook_subscription_deleted_no_matching_user_is_noop(tmp_path, monkeypatch):
    """Webhook should not fail if no user with that stripe_customer_id exists."""
    monkeypatch.setenv("SUBSCRIPTIONS_DB_PATH", str(tmp_path / "subs.json"))
    monkeypatch.setenv("USERS_DB_PATH", str(tmp_path / "users.json"))

    event = {
        "type": "customer.subscription.deleted",
        "data": {"object": {"id": "sub_unknown", "customer": "cus_unknown"}},
    }

    mgr = SubscriptionManager(SubscriptionConfig())
    result = mgr.handle_webhook(event)

    assert result["status"] == "handled"


# --- POST /subscriptions/portal endpoint tests ---


def test_portal_requires_auth():
    resp = _client.post("/subscriptions/portal")
    assert resp.status_code == 401


def test_portal_no_stripe_customer_returns_400(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test")
    token = _register_and_login("noportal@test.com")
    resp = _client.post("/subscriptions/portal", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 400
    assert "Stripe customer" in resp.json()["detail"]


@patch("cashflow_engine.subscriptions.router.StripeClient")
def test_portal_returns_url(mock_stripe_cls, monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test")
    monkeypatch.setenv("STRIPE_PRICE_ID_PRO", "price_pro")
    monkeypatch.setenv("FRONTEND_URL", "https://app.example.com")

    mock_stripe = MagicMock()
    mock_stripe.create_customer.return_value = "cus_portal1"
    mock_stripe.create_checkout_session.return_value = "https://checkout.stripe.com/session"
    mock_stripe.create_portal_session.return_value = "https://billing.stripe.com/portal/session"
    mock_stripe_cls.return_value = mock_stripe

    # First upgrade to get a stripe_customer_id stored
    token = _register_and_login("portal_user@test.com")
    _client.get("/subscriptions/upgrade", headers={"Authorization": f"Bearer {token}"})

    resp = _client.post("/subscriptions/portal", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json() == {"url": "https://billing.stripe.com/portal/session"}
    mock_stripe.create_portal_session.assert_called_once_with(
        "cus_portal1",
        return_url="https://app.example.com/dashboard",
    )


@patch("cashflow_engine.subscriptions.manager.stripe")
def test_stripe_client_create_portal_session(mock_stripe):
    mock_session = MagicMock()
    mock_session.url = "https://billing.stripe.com/portal/session123"
    mock_stripe.billing_portal.Session.create.return_value = mock_session

    client = StripeClient("sk_test")
    url = client.create_portal_session("cus_abc", "https://app.example.com/dashboard")

    mock_stripe.billing_portal.Session.create.assert_called_once_with(
        customer="cus_abc",
        return_url="https://app.example.com/dashboard",
    )
    assert url == "https://billing.stripe.com/portal/session123"


# --- customer.subscription.updated webhook tests ---


def test_handle_webhook_subscription_updated_active_upgrades_tier(tmp_path, monkeypatch):
    monkeypatch.setenv("SUBSCRIPTIONS_DB_PATH", str(tmp_path / "subs.json"))
    monkeypatch.setenv("USERS_DB_PATH", str(tmp_path / "users.json"))

    user = _make_user(tmp_path, "sub_updated@example.com", tier="free", stripe_customer_id="cus_upd1")

    event = {
        "type": "customer.subscription.updated",
        "data": {"object": {"customer": "cus_upd1", "status": "active"}},
    }

    mgr = SubscriptionManager(SubscriptionConfig())
    result = mgr.handle_webhook(event)

    assert result == {"status": "handled", "event_type": "customer.subscription.updated"}
    updated = auth_store.get_user_by_email("sub_updated@example.com")
    assert updated.tier == "pro"


def test_handle_webhook_subscription_updated_past_due_downgrades_tier(tmp_path, monkeypatch):
    monkeypatch.setenv("SUBSCRIPTIONS_DB_PATH", str(tmp_path / "subs.json"))
    monkeypatch.setenv("USERS_DB_PATH", str(tmp_path / "users.json"))

    user = _make_user(tmp_path, "pastdue@example.com", tier="pro", stripe_customer_id="cus_pastdue")

    event = {
        "type": "customer.subscription.updated",
        "data": {"object": {"customer": "cus_pastdue", "status": "past_due"}},
    }

    mgr = SubscriptionManager(SubscriptionConfig())
    result = mgr.handle_webhook(event)

    assert result == {"status": "handled", "event_type": "customer.subscription.updated"}
    updated = auth_store.get_user_by_email("pastdue@example.com")
    assert updated.tier == "free"


def test_handle_webhook_subscription_updated_unpaid_downgrades_tier(tmp_path, monkeypatch):
    monkeypatch.setenv("SUBSCRIPTIONS_DB_PATH", str(tmp_path / "subs.json"))
    monkeypatch.setenv("USERS_DB_PATH", str(tmp_path / "users.json"))

    user = _make_user(tmp_path, "unpaid@example.com", tier="pro", stripe_customer_id="cus_unpaid")

    event = {
        "type": "customer.subscription.updated",
        "data": {"object": {"customer": "cus_unpaid", "status": "unpaid"}},
    }

    mgr = SubscriptionManager(SubscriptionConfig())
    result = mgr.handle_webhook(event)

    assert result == {"status": "handled", "event_type": "customer.subscription.updated"}
    updated = auth_store.get_user_by_email("unpaid@example.com")
    assert updated.tier == "free"


def test_handle_webhook_subscription_updated_other_status_no_change(tmp_path, monkeypatch):
    monkeypatch.setenv("SUBSCRIPTIONS_DB_PATH", str(tmp_path / "subs.json"))
    monkeypatch.setenv("USERS_DB_PATH", str(tmp_path / "users.json"))

    user = _make_user(tmp_path, "trialing@example.com", tier="pro", stripe_customer_id="cus_trial2")

    event = {
        "type": "customer.subscription.updated",
        "data": {"object": {"customer": "cus_trial2", "status": "trialing"}},
    }

    mgr = SubscriptionManager(SubscriptionConfig())
    mgr.handle_webhook(event)

    updated = auth_store.get_user_by_email("trialing@example.com")
    assert updated.tier == "pro"


def test_handle_webhook_subscription_updated_no_matching_user_is_noop(tmp_path, monkeypatch):
    monkeypatch.setenv("SUBSCRIPTIONS_DB_PATH", str(tmp_path / "subs.json"))
    monkeypatch.setenv("USERS_DB_PATH", str(tmp_path / "users.json"))

    event = {
        "type": "customer.subscription.updated",
        "data": {"object": {"customer": "cus_nobody", "status": "active"}},
    }

    mgr = SubscriptionManager(SubscriptionConfig())
    result = mgr.handle_webhook(event)

    assert result["status"] == "handled"
