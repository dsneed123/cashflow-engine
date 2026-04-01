"""Trade execution log with atomic persistence to data/trades.json."""

from __future__ import annotations

import json
import os
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog
from filelock import FileLock

log = structlog.get_logger(__name__)

_DEFAULT_TRADES_PATH = "data/trades.json"


def _get_path() -> Path:
    return Path(os.environ.get("TRADES_DB_PATH", _DEFAULT_TRADES_PATH))


def _load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open() as f:
        return json.load(f)


def _save(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w") as f:
        json.dump(records, f, default=str, indent=2)
    os.replace(tmp, path)


def append_trade(
    *,
    module: str,
    symbol: str,
    side: str,
    amount: float,
    price: float,
    exchange: str,
    dry_run: bool,
    order_id: str | None = None,
) -> dict[str, Any]:
    """Append a trade record to trades.json and return the record."""
    record: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "module": module,
        "symbol": symbol,
        "side": side,
        "amount": amount,
        "price": price,
        "exchange": exchange,
        "dry_run": dry_run,
        "order_id": order_id,
    }
    path = _get_path()
    with FileLock(str(path.with_suffix(".lock"))):
        records = _load(path)
        records.append(record)
        _save(path, records)
    log.info("trade_logged", module=module, symbol=symbol, side=side, order_id=order_id)
    return record


def read_trades(limit: int = 50, offset: int = 0) -> list[dict]:
    """Return a paginated slice of trade records, newest first."""
    records = _load(_get_path())
    records_reversed = list(reversed(records))
    return records_reversed[offset: offset + limit]


def calculate_pnl(symbol: str | None = None) -> dict[str, Any]:
    """Calculate P&L using FIFO matching of buy/sell trades.

    Dry-run trades are excluded from P&L calculations and counted separately.
    Returns total realized P&L in USD, unrealized position value (cost basis),
    trade count, dry_run count, wins, losses, and win/loss ratio.

    When symbol is None, also includes a per-symbol breakdown under "symbols".
    """
    records = _load(_get_path())
    # Sort chronologically oldest-first for FIFO matching
    records.sort(key=lambda r: r["timestamp"])

    scoped = [r for r in records if symbol is None or r["symbol"] == symbol]
    dry_run_count = sum(1 for r in scoped if r.get("dry_run"))
    live = [r for r in scoped if not r.get("dry_run")]

    # Per-symbol buy queues: deque of [remaining_amount, buy_price]
    buy_queues: dict[str, deque] = {}
    symbol_stats: dict[str, dict] = {}

    total_realized = 0.0
    total_wins = 0
    total_losses = 0

    for trade in live:
        sym = trade["symbol"]
        if sym not in buy_queues:
            buy_queues[sym] = deque()
            symbol_stats[sym] = {
                "realized_pnl": 0.0,
                "unrealized_amount": 0.0,
                "unrealized_value": 0.0,
                "trade_count": 0,
                "wins": 0,
                "losses": 0,
            }

        symbol_stats[sym]["trade_count"] += 1

        if trade["side"] == "buy":
            buy_queues[sym].append([float(trade["amount"]), float(trade["price"])])
        elif trade["side"] == "sell":
            remaining = float(trade["amount"])
            sell_price = float(trade["price"])
            trade_pnl = 0.0
            matched = 0.0

            while remaining > 1e-12 and buy_queues[sym]:
                lot = buy_queues[sym][0]
                fill = min(lot[0], remaining)
                trade_pnl += (sell_price - lot[1]) * fill
                matched += fill
                remaining -= fill
                lot[0] -= fill
                if lot[0] <= 1e-12:
                    buy_queues[sym].popleft()

            if matched > 1e-12:
                total_realized += trade_pnl
                symbol_stats[sym]["realized_pnl"] += trade_pnl
                if trade_pnl > 0:
                    total_wins += 1
                    symbol_stats[sym]["wins"] += 1
                else:
                    total_losses += 1
                    symbol_stats[sym]["losses"] += 1

    # Compute unrealized position value (cost basis of remaining buy lots)
    total_unrealized = 0.0
    for sym, queue in buy_queues.items():
        sym_amount = sum(lot[0] for lot in queue)
        sym_value = sum(lot[0] * lot[1] for lot in queue)
        total_unrealized += sym_value
        if sym in symbol_stats:
            symbol_stats[sym]["unrealized_amount"] = sym_amount
            symbol_stats[sym]["unrealized_value"] = sym_value

    win_loss_ratio: float | None = (
        total_wins / total_losses if total_losses > 0 else None
    )

    result: dict[str, Any] = {
        "realized_pnl": round(total_realized, 8),
        "unrealized_value": round(total_unrealized, 8),
        "trade_count": len(live),
        "dry_run_count": dry_run_count,
        "wins": total_wins,
        "losses": total_losses,
        "win_loss_ratio": win_loss_ratio,
    }

    if symbol is None:
        result["symbols"] = {
            sym: {
                "realized_pnl": round(stats["realized_pnl"], 8),
                "unrealized_amount": stats["unrealized_amount"],
                "unrealized_value": round(stats["unrealized_value"], 8),
                "trade_count": stats["trade_count"],
                "wins": stats["wins"],
                "losses": stats["losses"],
                "win_loss_ratio": (
                    stats["wins"] / stats["losses"] if stats["losses"] > 0 else None
                ),
            }
            for sym, stats in symbol_stats.items()
        }

    return result
