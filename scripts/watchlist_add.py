#!/usr/bin/env python3
"""Add or update a watchlist item YAML entry from a stock symbol."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, ".")

from app.watchlists.providers import (
    InstrumentLookupError,
    instrument_draft_to_item,
    instrument_draft_to_json,
    resolve_instrument,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("watchlist_name")
    parser.add_argument("symbol")
    parser.add_argument("--file", default="config/watchlists/custom/watchlists.yaml")
    parser.add_argument("--priority", choices=["high", "medium", "low"], default="medium")
    holding_group = parser.add_mutually_exclusive_group()
    holding_group.add_argument("--holding", dest="holding", action="store_true", default=False)
    holding_group.add_argument("--no-holding", dest="holding", action="store_false")
    parser.add_argument("--notes")
    parser.add_argument("--provider", choices=["auto", "sina", "eastmoney", "yahoo", "stooq"], default="auto")
    parser.add_argument("--name")
    parser.add_argument("--local-name")
    parser.add_argument("--market")
    parser.add_argument("--exchange")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"watchlists": []}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Watchlist file '{path}' must contain a mapping.")
    watchlists = data.setdefault("watchlists", [])
    if not isinstance(watchlists, list):
        raise ValueError(f"Watchlist file '{path}' must define 'watchlists' as a list.")
    return data


def _find_or_create_watchlist(data: dict[str, Any], name: str) -> dict[str, Any]:
    watchlists = data.setdefault("watchlists", [])
    for watchlist in watchlists:
        if isinstance(watchlist, dict) and watchlist.get("name") == name:
            watchlist.setdefault("items", [])
            return watchlist
    watchlist = {"name": name, "is_active": True, "items": []}
    watchlists.append(watchlist)
    return watchlist


def _item_key(item: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(item.get("market") or "").upper(),
        str(item.get("exchange") or "").upper(),
        str(item.get("ticker") or "").upper(),
    )


def _upsert_item(watchlist: dict[str, Any], item: dict[str, Any]) -> str:
    items = watchlist.setdefault("items", [])
    target_key = _item_key(item)
    for index, existing in enumerate(items):
        if isinstance(existing, dict) and _item_key(existing) == target_key:
            merged = {**existing, **item}
            items[index] = {key: value for key, value in merged.items() if value is not None}
            return "updated"
    items.append({key: value for key, value in item.items() if value is not None})
    return "created"


def main() -> None:
    args = parse_args()
    try:
        draft = resolve_instrument(
            args.symbol,
            provider=args.provider,
            market=args.market,
            exchange=args.exchange,
            name=args.name,
            local_name=args.local_name,
        )
    except InstrumentLookupError as exc:
        raise SystemExit(f"Failed to resolve symbol. Provide --name to use manual fallback. {exc}") from exc

    item = instrument_draft_to_item(draft)
    item.update(
        {
            "priority": args.priority,
            "is_holding": args.holding,
            "notes": args.notes,
        }
    )
    path = Path(args.file)
    data = _load_yaml(path)
    watchlist = _find_or_create_watchlist(data, args.watchlist_name)
    action = _upsert_item(watchlist, item)

    print(f"{action}: {draft.market}:{draft.exchange}:{draft.ticker}")
    print(instrument_draft_to_json(draft))
    if args.dry_run:
        print("\nDry run YAML:")
        print(yaml.safe_dump(data, allow_unicode=True, sort_keys=False))
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"Wrote {path}")
    print("Next: python scripts/sync_watchlists.py")


if __name__ == "__main__":
    main()
