"""Global configuration model."""

from pydantic import BaseModel, Field


class TradingConfig(BaseModel):
    enabled: bool = False
    max_position_usd: float = Field(default=1000.0, gt=0)
    dry_run: bool = True


class ArbitrageConfig(BaseModel):
    enabled: bool = False
    min_spread_pct: float = Field(default=0.5, gt=0)
    dry_run: bool = True


class SubscriptionConfig(BaseModel):
    enabled: bool = True
    trial_days: int = Field(default=14, ge=0)


class EngineConfig(BaseModel):
    trading: TradingConfig = TradingConfig()
    arbitrage: ArbitrageConfig = ArbitrageConfig()
    subscriptions: SubscriptionConfig = SubscriptionConfig()
