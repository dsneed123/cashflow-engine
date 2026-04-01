"""Trade execution log with atomic persistence to data/trades.json."""

from __future__ import annotations

import json
import os
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
