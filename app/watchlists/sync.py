from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.instrument import Instrument
from app.models.watchlist import Watchlist, WatchlistItem
from app.watchlists.config import WatchlistDefinition, WatchlistItemDefinition


@dataclass
class WatchlistSyncResult:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    deactivated: list[str] = field(default_factory=list)

    @property
    def changed_count(self) -> int:
        return len(self.created) + len(self.updated) + len(self.deactivated)


def _instrument_identity(item: WatchlistItemDefinition) -> str:
    return f"{item.market}:{item.exchange}:{item.ticker}"


def _get_instrument(session: Session, item: WatchlistItemDefinition) -> Instrument | None:
    return (
        session.query(Instrument)
        .filter_by(market=item.market, exchange=item.exchange, ticker=item.ticker)
        .first()
    )


def _upsert_instrument(
    session: Session,
    item: WatchlistItemDefinition,
    result: WatchlistSyncResult,
    *,
    dry_run: bool,
) -> Instrument | None:
    instrument = _get_instrument(session, item)
    identity = _instrument_identity(item)
    data = {
        "market": item.market,
        "ticker": item.ticker,
        "exchange": item.exchange,
        "company_name": item.company_name,
        "local_name": item.local_name,
        "aliases": json.dumps(item.aliases, ensure_ascii=False) if item.aliases else None,
        "sector": item.sector,
        "industry": item.industry,
        "currency": item.currency,
        "is_active": True,
    }
    if instrument is None:
        result.created.append(f"instrument:{identity}")
        if dry_run:
            return None
        instrument = Instrument(**data)
        session.add(instrument)
        session.flush()
        return instrument

    changed = False
    for key, value in data.items():
        if getattr(instrument, key) != value:
            changed = True
            if not dry_run:
                setattr(instrument, key, value)
    if changed:
        result.updated.append(f"instrument:{identity}")
    return instrument


def _upsert_watchlist(
    session: Session,
    definition: WatchlistDefinition,
    result: WatchlistSyncResult,
    *,
    dry_run: bool,
) -> Watchlist | None:
    watchlist = session.query(Watchlist).filter_by(name=definition.name).first()
    if watchlist is None:
        result.created.append(f"watchlist:{definition.name}")
        if dry_run:
            return None
        watchlist = Watchlist(
            name=definition.name,
            description=definition.description,
            is_active=definition.is_active,
        )
        session.add(watchlist)
        session.flush()
        return watchlist

    changed = False
    for key, value in {
        "description": definition.description,
        "is_active": definition.is_active,
    }.items():
        if getattr(watchlist, key) != value:
            changed = True
            if not dry_run:
                setattr(watchlist, key, value)
    if changed:
        result.updated.append(f"watchlist:{definition.name}")
    return watchlist


def _upsert_watchlist_item(
    session: Session,
    watchlist: Watchlist,
    instrument: Instrument,
    item: WatchlistItemDefinition,
    result: WatchlistSyncResult,
    *,
    dry_run: bool,
) -> None:
    existing = (
        session.query(WatchlistItem)
        .filter_by(watchlist_id=watchlist.watchlist_id, instrument_id=instrument.instrument_id)
        .first()
    )
    identity = f"watchlist_item:{watchlist.name}:{_instrument_identity(item)}"
    data = {
        "priority": item.priority,
        "is_active": item.is_active,
        "is_holding": item.is_holding,
        "notes": item.notes,
    }
    if existing is None:
        result.created.append(identity)
        if dry_run:
            return
        session.add(
            WatchlistItem(
                watchlist_id=watchlist.watchlist_id,
                instrument_id=instrument.instrument_id,
                **data,
            )
        )
        session.flush()
        return

    changed = False
    for key, value in data.items():
        if getattr(existing, key) != value:
            changed = True
            if not dry_run:
                setattr(existing, key, value)
    if changed:
        if not dry_run:
            existing.updated_at = datetime.now(timezone.utc)
        result.updated.append(identity)


def sync_watchlists(
    session: Session,
    definitions: list[WatchlistDefinition],
    *,
    deactivate_missing: bool = False,
    dry_run: bool = False,
) -> WatchlistSyncResult:
    result = WatchlistSyncResult()
    configured_items: dict[str, set[str]] = {}

    for definition in definitions:
        watchlist = _upsert_watchlist(session, definition, result, dry_run=dry_run)
        configured_items.setdefault(definition.name, set())
        for item in definition.items:
            configured_items[definition.name].add(_instrument_identity(item))
            instrument = _upsert_instrument(session, item, result, dry_run=dry_run)
            if watchlist is not None and instrument is not None:
                _upsert_watchlist_item(session, watchlist, instrument, item, result, dry_run=dry_run)

    if deactivate_missing:
        for definition in definitions:
            watchlist = session.query(Watchlist).filter_by(name=definition.name).first()
            if watchlist is None:
                continue
            configured = configured_items.get(definition.name, set())
            existing_items = (
                session.query(WatchlistItem)
                .filter_by(watchlist_id=watchlist.watchlist_id, is_active=True)
                .all()
            )
            for existing in existing_items:
                instrument = session.get(Instrument, existing.instrument_id)
                if instrument is None:
                    continue
                identity = f"{instrument.market}:{instrument.exchange}:{instrument.ticker}"
                if identity in configured:
                    continue
                result.deactivated.append(f"watchlist_item:{watchlist.name}:{identity}")
                if not dry_run:
                    existing.is_active = False
                    existing.updated_at = datetime.now(timezone.utc)

    if not dry_run:
        session.flush()
    return result
