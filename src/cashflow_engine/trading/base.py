"""Trading module with CCXT-based exchange integration."""

from __future__ import annotations

import ccxt
import structlog

from cashflow_engine.config import TradingConfig

log = structlog.get_logger(__name__)


class ExchangeClient:
    """Wrapper around a ccxt exchange instance."""

    def __init__(self, config: TradingConfig) -> None:
        exchange_class = getattr(ccxt, config.exchange_id)
        self.exchange = exchange_class({
            "apiKey": config.api_key or "",
            "secret": config.api_secret or "",
        })
        self.dry_run = config.dry_run

    def fetch_ticker(self, symbol: str) -> dict:
        return self.exchange.fetch_ticker(symbol)

    def fetch_ohlcv(self, symbol: str, timeframe: str = "1h", limit: int = 24) -> list:
        return self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)

    def place_order(self, symbol: str, side: str, amount: float) -> dict:
        if self.dry_run:
            ticker = self.fetch_ticker(symbol)
            price = ticker["last"]
            return {
                "id": "dry-run",
                "symbol": symbol,
                "side": side,
                "amount": amount,
                "price": price,
                "status": "simulated",
            }
        return self.exchange.create_market_order(symbol, side, amount)

    def get_positions(self) -> list[dict]:
        if self.dry_run:
            return []
        try:
            return self.exchange.fetch_positions() or []
        except Exception:
            log.warning("fetch_positions_failed")
            return []


class TradingModule:
    def __init__(self, config: TradingConfig) -> None:
        self.config = config
        self.client = ExchangeClient(config)

    def status(self) -> dict:
        return {"enabled": self.config.enabled, "dry_run": self.config.dry_run}

    def run(self) -> dict:
        log.info("trading_run", dry_run=self.config.dry_run)

        symbol = "BTC/USDT"
        try:
            ticker = self.client.fetch_ticker(symbol)
            price = ticker["last"]

            # Compute 24h MA from hourly candles; candle format: [ts, open, high, low, close, vol]
            ohlcv = self.client.fetch_ohlcv(symbol, "1h", limit=24)
            ma_24h = sum(candle[4] for candle in ohlcv) / len(ohlcv)

            signal = "buy" if price > ma_24h else "sell"
            amount = self.config.max_position_usd / price

            order = self.client.place_order(symbol, signal, amount)
            log.info("trading_signal", symbol=symbol, price=price, ma_24h=ma_24h, signal=signal)

            return {
                "orders_placed": 1,
                "dry_run": self.config.dry_run,
                "symbol": symbol,
                "price": price,
                "ma_24h": ma_24h,
                "signal": signal,
                "order": order,
            }
        except Exception as e:
            log.error("trading_error", error=str(e))
            return {"orders_placed": 0, "dry_run": self.config.dry_run, "error": str(e)}
