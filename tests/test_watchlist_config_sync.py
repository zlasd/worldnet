from pathlib import Path

from app.models.instrument import Instrument
from app.models.watchlist import Watchlist, WatchlistItem
from app.watchlists.config import load_watchlist_definitions
from app.watchlists.sync import sync_watchlists


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def test_load_watchlist_definitions_merges_custom_override(tmp_path):
    default_dir = tmp_path / "default"
    custom_dir = tmp_path / "custom"
    _write(
        default_dir / "watchlists.yaml",
        """
        watchlists:
          - name: A股观察
            description: default
            items:
              - market: CN
                exchange: SSE
                ticker: "600519"
                company_name: 贵州茅台
                currency: CNY
                priority: medium
        """,
    )
    _write(
        custom_dir / "watchlists.yaml",
        """
        watchlists:
          - name: A股观察
            description: custom
            items:
              - market: CN
                exchange: SSE
                ticker: "600519"
                company_name: 贵州茅台
                currency: CNY
                priority: high
                is_holding: true
        """,
    )

    definitions = load_watchlist_definitions(default_dir=default_dir, custom_dir=custom_dir)

    assert len(definitions) == 1
    assert definitions[0].description == "custom"
    assert definitions[0].items[0].priority == "high"
    assert definitions[0].items[0].is_holding is True


def test_sync_watchlists_creates_and_updates_items(session, tmp_path):
    config_dir = tmp_path / "custom"
    _write(
        config_dir / "watchlists.yaml",
        """
        watchlists:
          - name: A股观察
            items:
              - market: CN
                exchange: SSE
                ticker: "600519"
                company_name: 贵州茅台
                local_name: 贵州茅台
                aliases: [茅台]
                currency: CNY
                priority: high
                is_holding: true
                notes: core
        """,
    )
    definitions = load_watchlist_definitions(default_dir=tmp_path / "default", custom_dir=config_dir)

    result = sync_watchlists(session, definitions)

    assert "watchlist:A股观察" in result.created
    instrument = session.query(Instrument).filter_by(ticker="600519").one()
    item = session.query(WatchlistItem).one()
    assert instrument.company_name == "贵州茅台"
    assert item.priority == "high"
    assert item.is_holding is True
    assert item.is_active is True

    definitions[0].items[0].priority = "medium"
    definitions[0].items[0].notes = "updated"
    result = sync_watchlists(session, definitions)

    assert result.updated
    assert item.priority == "medium"
    assert item.notes == "updated"


def test_sync_watchlists_deactivates_missing_items(session):
    instrument = Instrument(
        market="CN",
        exchange="SSE",
        ticker="600519",
        company_name="贵州茅台",
        currency="CNY",
    )
    watchlist = Watchlist(name="A股观察")
    session.add_all([instrument, watchlist])
    session.flush()
    item = WatchlistItem(watchlist_id=watchlist.watchlist_id, instrument_id=instrument.instrument_id)
    session.add(item)
    session.flush()

    definitions = load_watchlist_definitions(default_dir=Path("/missing"), custom_dir=Path("/missing"))
    definitions.append(type("Definition", (), {"name": "A股观察", "description": None, "is_active": True, "items": []})())

    result = sync_watchlists(session, definitions, deactivate_missing=True)

    assert result.deactivated == ["watchlist_item:A股观察:CN:SSE:600519"]
    assert item.is_active is False


def test_sync_watchlists_dry_run_does_not_write(session, tmp_path):
    config_dir = tmp_path / "custom"
    _write(
        config_dir / "watchlists.yaml",
        """
        watchlists:
          - name: A股观察
            items:
              - market: CN
                exchange: SSE
                ticker: "600519"
                company_name: 贵州茅台
                currency: CNY
        """,
    )
    definitions = load_watchlist_definitions(default_dir=tmp_path / "default", custom_dir=config_dir)

    result = sync_watchlists(session, definitions, dry_run=True)

    assert result.created
    assert session.query(Watchlist).count() == 0
