# cashflow-engine

Automated ethical money-making SaaS platform with trading, arbitrage, and subscription revenue streams.

## Modules

| Module | Description |
|---|---|
| `trading` | Exchange-based trading (dry-run safe, pluggable client) |
| `arbitrage` | Cross-venue spread detection |
| `subscriptions` | Subscriber lifecycle and renewal processing |

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Show module status
cashflow-engine status

# Run one revenue cycle
cashflow-engine run
```

## Development

```bash
# Lint
ruff check src tests

# Test with coverage
pytest
```

## Configuration

All modules are configured via `EngineConfig` (see `src/cashflow_engine/config.py`).
Trading and arbitrage default to `dry_run=True` and `enabled=False` — flip both flags deliberately before connecting live credentials.
