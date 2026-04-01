"""Tests for startup secret validation."""

import pytest
from fastapi.testclient import TestClient

import cashflow_engine.auth.security as security
from cashflow_engine.auth.security import validate_jwt_secret, _DEV_SECRET
from cashflow_engine.config import SubscriptionConfig, validate_subscription_config


# ---------------------------------------------------------------------------
# validate_jwt_secret unit tests
# ---------------------------------------------------------------------------


def test_validate_jwt_secret_raises_on_default():
    with pytest.raises(ValueError, match="default dev value"):
        validate_jwt_secret(_DEV_SECRET)


def test_validate_jwt_secret_raises_on_short_secret():
    with pytest.raises(ValueError, match="at least 32 characters"):
        validate_jwt_secret("too-short")


def test_validate_jwt_secret_passes_on_valid_secret():
    # Should not raise
    validate_jwt_secret("a-valid-secret-that-is-long-enough-32!!")


def test_validate_jwt_secret_raises_on_exactly_31_chars():
    with pytest.raises(ValueError, match="at least 32 characters"):
        validate_jwt_secret("a" * 31)


def test_validate_jwt_secret_passes_on_exactly_32_chars():
    validate_jwt_secret("a" * 32)


# ---------------------------------------------------------------------------
# validate_subscription_config unit tests
# ---------------------------------------------------------------------------


def test_validate_subscription_config_raises_when_enabled_without_key():
    cfg = SubscriptionConfig(enabled=True, stripe_secret_key=None)
    with pytest.raises(ValueError, match="STRIPE_SECRET_KEY must be set"):
        validate_subscription_config(cfg)


def test_validate_subscription_config_passes_when_enabled_with_key():
    cfg = SubscriptionConfig(enabled=True, stripe_secret_key="sk_test_something")
    validate_subscription_config(cfg)  # should not raise


def test_validate_subscription_config_passes_when_disabled_without_key():
    cfg = SubscriptionConfig(enabled=False, stripe_secret_key=None)
    validate_subscription_config(cfg)  # should not raise


# ---------------------------------------------------------------------------
# App startup integration tests
# ---------------------------------------------------------------------------


def test_app_startup_fails_with_default_jwt_secret(monkeypatch):
    """Lifespan must raise if JWT_SECRET_KEY is the insecure default."""
    monkeypatch.setattr(security, "_SECRET_KEY", _DEV_SECRET)
    from cashflow_engine.api.app import app

    with pytest.raises(ValueError, match="default dev value"):
        with TestClient(app):
            pass


def test_app_startup_fails_without_stripe_key(monkeypatch):
    """Lifespan must raise if subscriptions are enabled but STRIPE_SECRET_KEY is absent."""
    # JWT must be valid so we only trigger the Stripe error
    monkeypatch.setattr(security, "_SECRET_KEY", "a-valid-secret-that-is-long-enough-32!!")
    from cashflow_engine.api.app import _engine

    monkeypatch.setattr(_engine.subscriptions.config, "stripe_secret_key", None)
    from cashflow_engine.api.app import app

    with pytest.raises(ValueError, match="STRIPE_SECRET_KEY must be set"):
        with TestClient(app):
            pass
