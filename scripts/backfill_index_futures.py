#!/usr/bin/env python3
"""Idempotently backfill official index-futures basis data and paper portfolios."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date

sys.path.insert(0, ".")

from app.db.session import get_db_session
from app.digests.config import PaperStrategyConfig
from app.index_futures.paper import process_paper_strategy
from app.index_futures.service import update_basis_snapshots


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    parser.add_argument("--history-days", type=int, default=252)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--skip-paper-strategy", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    if args.history_days < 20:
        raise SystemExit("--history-days must be at least 20")
    with get_db_session() as session:
        basis = update_basis_snapshots(
            session,
            as_of=args.as_of,
            history_days=args.history_days,
            force_backfill=args.force,
        )
        strategy_trades = 0
        strategy_dates = 0
        warnings = list(basis.warnings)
        if basis.trade_date is not None and not args.skip_paper_strategy:
            strategy = process_paper_strategy(
                session,
                config=PaperStrategyConfig(),
                up_to=basis.trade_date,
            )
            strategy_trades = strategy.trades
            strategy_dates = len(strategy.processed_dates)
            warnings.extend(strategy.warnings)
        print(
            json.dumps(
                {
                    "trade_date": basis.trade_date.isoformat() if basis.trade_date else None,
                    "fetched": basis.fetched,
                    "upserted": basis.upserted,
                    "paper_processed_dates": strategy_dates,
                    "paper_trades": strategy_trades,
                    "warnings": list(dict.fromkeys(warnings)),
                },
                ensure_ascii=False,
            )
        )
        return 0 if basis.trade_date is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
