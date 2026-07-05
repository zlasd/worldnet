from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator


class WatchlistItemDefinition(BaseModel):
    market: str
    exchange: str
    ticker: str
    company_name: str
    local_name: str | None = None
    aliases: list[str] | None = None
    sector: str | None = None
    industry: str | None = None
    currency: str
    priority: str = "medium"
    is_holding: bool = False
    is_active: bool = True
    notes: str | None = None

    @model_validator(mode="after")
    def normalize_identity(self) -> "WatchlistItemDefinition":
        self.market = self.market.upper().strip()
        self.exchange = self.exchange.upper().strip()
        self.ticker = self.ticker.upper().strip()
        if self.market == "HK" and self.ticker.isdigit():
            self.ticker = str(int(self.ticker)).zfill(4)
        self.currency = self.currency.upper().strip()
        return self


class WatchlistDefinition(BaseModel):
    name: str
    description: str | None = None
    is_active: bool = True
    items: list[WatchlistItemDefinition] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_name(self) -> "WatchlistDefinition":
        if not self.name.strip():
            raise ValueError("watchlist name cannot be empty.")
        self.name = self.name.strip()
        return self


def _iter_watchlist_files(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    return sorted(directory.glob("*.yaml")) + sorted(directory.glob("*.yml"))


def _read_watchlist_file(path: Path) -> list[dict[str, Any]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Watchlist config file '{path}' must contain a mapping.")
    watchlists = data.get("watchlists", [])
    if not isinstance(watchlists, list):
        raise ValueError(f"Watchlist config file '{path}' must define 'watchlists' as a list.")
    normalized: list[dict[str, Any]] = []
    for item in watchlists:
        if not isinstance(item, dict):
            raise ValueError(f"Watchlist config file '{path}' contains a non-mapping entry.")
        normalized.append(item)
    return normalized


def _merge_dict(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if value is None:
            continue
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_watchlist_definitions(
    default_dir: str | Path = "config/watchlists/default",
    custom_dir: str | Path = "config/watchlists/custom",
) -> list[WatchlistDefinition]:
    merged: dict[str, dict[str, Any]] = {}
    for path in [*_iter_watchlist_files(Path(default_dir)), *_iter_watchlist_files(Path(custom_dir))]:
        for watchlist_data in _read_watchlist_file(path):
            name = watchlist_data.get("name")
            if not isinstance(name, str) or not name.strip():
                raise ValueError(f"Watchlist config file '{path}' contains a watchlist without a valid name.")
            existing = merged.get(name, {})
            merged[name] = _merge_dict(existing, watchlist_data)

    return [WatchlistDefinition.model_validate(merged[name]) for name in sorted(merged)]
