"""Subscriptions router: upgrade endpoint."""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, status

from cashflow_engine.auth import models as auth_models, store as auth_store
from cashflow_engine.auth.router import get_current_user
from cashflow_engine.subscriptions.manager import StripeClient

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


def _get_stripe_client() -> StripeClient:
    key = os.environ.get("STRIPE_SECRET_KEY")
    if not key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe not configured",
        )
    return StripeClient(key)


@router.post("/portal")
def portal(current_user: auth_models.User = Depends(get_current_user)) -> dict:
    if current_user.stripe_customer_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No Stripe customer associated with this account",
        )
    stripe_client = _get_stripe_client()
    frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:3000")
    portal_url = stripe_client.create_portal_session(
        current_user.stripe_customer_id,
        return_url=f"{frontend_url}/dashboard",
    )
    return {"url": portal_url}


@router.get("/upgrade")
def upgrade(current_user: auth_models.User = Depends(get_current_user)) -> dict:
    stripe_client = _get_stripe_client()

    customer_id = current_user.stripe_customer_id
    if customer_id is None:
        customer_id = stripe_client.create_customer(current_user.email, current_user.email)
        current_user.stripe_customer_id = customer_id
        auth_store.update_user(current_user)

    price_id = os.environ.get("STRIPE_PRICE_ID_PRO")
    if not price_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe price not configured",
        )

    frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:3000")
    checkout_url = stripe_client.create_checkout_session(
        customer_id,
        price_id,
        success_url=f"{frontend_url}/upgrade/success",
        cancel_url=f"{frontend_url}/upgrade/cancel",
    )
    return {"checkout_url": checkout_url}
