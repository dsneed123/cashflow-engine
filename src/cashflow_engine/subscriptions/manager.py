"""Subscription lifecycle manager with Stripe billing integration."""

from __future__ import annotations

import json
import os
from pathlib import Path

import stripe
import structlog

from cashflow_engine.auth import store as user_store
from cashflow_engine.config import SubscriptionConfig

log = structlog.get_logger(__name__)

_DEFAULT_SUBSCRIPTIONS_PATH = "data/subscribers.json"


class StripeClient:
    """Thin wrapper around the Stripe Python SDK."""

    def __init__(self, secret_key: str) -> None:
        stripe.api_key = secret_key

    def create_customer(self, email: str, name: str) -> str:
        customer = stripe.Customer.create(email=email, name=name)
        return customer.id

    def create_subscription(self, customer_id: str, price_id: str) -> str:
        subscription = stripe.Subscription.create(
            customer=customer_id,
            items=[{"price": price_id}],
        )
        return subscription.id

    def cancel_subscription(self, subscription_id: str) -> None:
        stripe.Subscription.cancel(subscription_id)

    def get_subscription(self, subscription_id: str) -> dict:
        return stripe.Subscription.retrieve(subscription_id)

    def create_checkout_session(
        self, customer_id: str, price_id: str, success_url: str, cancel_url: str
    ) -> str:
        session = stripe.checkout.Session.create(
            customer=customer_id,
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
        )
        return session.url


class SubscriptionManager:
    def __init__(self, config: SubscriptionConfig) -> None:
        self.config = config
        self._path = Path(os.environ.get("SUBSCRIPTIONS_DB_PATH", _DEFAULT_SUBSCRIPTIONS_PATH))
        self._stripe: StripeClient | None = (
            StripeClient(config.stripe_secret_key) if config.stripe_secret_key else None
        )
        self._subscribers: list[dict] = self._load()

    def _load(self) -> list[dict]:
        if not self._path.exists():
            return []
        with self._path.open() as f:
            return json.load(f)

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        with tmp.open("w") as f:
            json.dump(self._subscribers, f, default=str, indent=2)
        os.replace(tmp, self._path)

    def status(self) -> dict:
        return {"enabled": self.config.enabled, "subscriber_count": len(self._subscribers)}

    def add_subscriber(
        self, subscriber_id: str, email: str | None = None, name: str | None = None
    ) -> dict:
        record: dict = {
            "id": subscriber_id,
            "trial_days_remaining": self.config.trial_days,
            "stripe_customer_id": None,
            "stripe_subscription_id": None,
        }
        if self._stripe and email and name:
            try:
                record["stripe_customer_id"] = self._stripe.create_customer(email, name)
            except Exception:
                log.exception("stripe_create_customer_failed", subscriber_id=subscriber_id)
        self._subscribers.append(record)
        log.info("subscriber_added", subscriber_id=subscriber_id)
        self._save()
        return record

    def process_renewals(self) -> dict:
        log.info("processing_renewals", count=len(self._subscribers))

        renewed = 0
        failed = 0
        for subscriber in self._subscribers:
            sub_id = subscriber.get("stripe_subscription_id")
            if sub_id:
                if not self._stripe:
                    continue
                try:
                    subscription = self._stripe.get_subscription(sub_id)
                    if subscription["status"] in ("active", "trialing"):
                        renewed += 1
                    else:
                        log.warning(
                            "subscription_not_active",
                            subscriber_id=subscriber["id"],
                            status=subscription["status"],
                        )
                        failed += 1
                except Exception:
                    log.exception(
                        "stripe_get_subscription_failed", subscriber_id=subscriber["id"]
                    )
                    failed += 1
            else:
                subscriber["trial_days_remaining"] = subscriber.get("trial_days_remaining", 0) - 1
                if (
                    self._stripe
                    and subscriber.get("stripe_customer_id")
                    and subscriber["trial_days_remaining"] == 0
                    and self.config.stripe_price_id_pro
                ):
                    try:
                        new_sub_id = self._stripe.create_subscription(
                            subscriber["stripe_customer_id"],
                            self.config.stripe_price_id_pro,
                        )
                        subscriber["stripe_subscription_id"] = new_sub_id
                        renewed += 1
                        log.info("subscription_created", subscriber_id=subscriber["id"])
                    except Exception:
                        log.exception(
                            "stripe_create_subscription_failed", subscriber_id=subscriber["id"]
                        )
                        failed += 1

        self._save()
        return {"renewed": renewed, "failed": failed, "total": len(self._subscribers)}

    def create_checkout_session(self, subscriber_id: str, price_id: str) -> str:
        if not self._stripe:
            raise ValueError("Stripe not configured")
        subscriber = next((s for s in self._subscribers if s["id"] == subscriber_id), None)
        if subscriber is None:
            raise ValueError(f"Subscriber {subscriber_id!r} not found")
        customer_id = subscriber.get("stripe_customer_id")
        if not customer_id:
            raise ValueError(f"Subscriber {subscriber_id!r} has no Stripe customer")
        frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:3000")
        return self._stripe.create_checkout_session(
            customer_id,
            price_id,
            success_url=f"{frontend_url}/billing/success",
            cancel_url=f"{frontend_url}/billing/cancel",
        )

    def handle_webhook(self, payload: bytes, sig_header: str) -> dict:
        webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET")
        if not webhook_secret:
            raise ValueError("STRIPE_WEBHOOK_SECRET not configured")
        try:
            event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
        except Exception as exc:
            raise ValueError(f"Webhook signature verification failed: {exc}") from exc

        event_type = event["type"]
        event_data = event["data"]["object"]

        if event_type == "checkout.session.completed":
            customer_id = event_data.get("customer")
            subscription_id = event_data.get("subscription")
            if customer_id and subscription_id:
                for subscriber in self._subscribers:
                    if subscriber.get("stripe_customer_id") == customer_id:
                        subscriber["stripe_subscription_id"] = subscription_id
                        log.info("checkout_session_completed", subscriber_id=subscriber["id"])
                        user_store.set_tier(subscriber["id"], "pro")
                        break
                self._save()
        elif event_type == "customer.subscription.deleted":
            subscription_id = event_data.get("id")
            if subscription_id:
                for subscriber in self._subscribers:
                    if subscriber.get("stripe_subscription_id") == subscription_id:
                        subscriber["stripe_subscription_id"] = None
                        log.info("subscription_deleted", subscriber_id=subscriber["id"])
                        user_store.set_tier(subscriber["id"], "free")
                        break
                self._save()

        return {"status": "handled", "event_type": event_type}
