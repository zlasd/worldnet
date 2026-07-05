#!/usr/bin/env python3
"""Sync YAML watchlist definitions into the database."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, ".")

from app.db.session import get_db_session
from app.watchlists.config import load_watchlist_definitions
from app.watchlists.sync import sync_watchlists


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--default-dir", default="config/watchlists/default")
    parser.add_argument("--custom-dir", default="config/watchlists/custom")
    parser.add_argument("--deactivate-missing", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    definitions = load_watchlist_definitions(
        default_dir=Path(args.default_dir),
        custom_dir=Path(args.custom_dir),
    )
    with get_db_session() as session:
        result = sync_watchlists(
            session,
            definitions,
            deactivate_missing=args.deactivate_missing,
            dry_run=args.dry_run,
        )
        if args.dry_run:
            session.rollback()

    print(f"Loaded {len(definitions)} watchlist definition(s).")
    for label, values in [
        ("created", result.created),
        ("updated", result.updated),
        ("deactivated", result.deactivated),
    ]:
        print(f"{label}: {len(values)}")
        for value in values:
            print(f"  - {value}")


if __name__ == "__main__":
    main()
