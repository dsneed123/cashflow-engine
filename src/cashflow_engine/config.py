"""Global configuration model."""

import os

from pydantic import BaseModel, Field


class TradingConfig(BaseModel):
    enabled: bool = False
    max_position_usd: float = Field(default=1000.0, gt=0)
    dry_run: bool = True
    exchange_id: str = "binance"
    api_key: str | None = Field(default_factory=lambda: os.environ.get("EXCHANGE_API_KEY"))
    api_secret: str | None = Field(default_factory=lambda: os.environ.get("EXCHANGE_API_SECRET"))


class ArbitrageConfig(BaseModel):
    enabled: bool = False
    min_spread_pct: float = Field(default=0.5, gt=0)
    dry_run: bool = True


class SubscriptionConfig(BaseModel):
    enabled: bool = True
    trial_days: int = Field(default=14, ge=0)
    stripe_secret_key: str | None = Field(
        default_factory=lambda: os.environ.get("STRIPE_SECRET_KEY")
    )
    stripe_price_id_pro: str | None = Field(
        default_factory=lambda: os.environ.get("STRIPE_PRICE_ID_PRO")
    )


class EngineConfig(BaseModel):
    trading: TradingConfig = TradingConfig()
    arbitrage: ArbitrageConfig = ArbitrageConfig()
    subscriptions: SubscriptionConfig = SubscriptionConfig()
    cors_origins: list[str] = Field(
        default_factory=lambda: [o.strip() for o in os.environ.get("CORS_ORIGINS", "*").split(",")]
    )
