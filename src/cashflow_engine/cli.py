"""Minimal CLI entry point."""

from __future__ import annotations

import json
import sys

import structlog

from cashflow_engine.core.engine import CashflowEngine

log = structlog.get_logger(__name__)


def main() -> None:
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(20),  # INFO
    )
    engine = CashflowEngine()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"

    if cmd == "status":
        print(json.dumps(engine.status(), indent=2))
    elif cmd == "run":
        result = engine.run_cycle()
        print(json.dumps(result, indent=2))
    else:
        print(f"Unknown command: {cmd}. Use 'status' or 'run'.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
