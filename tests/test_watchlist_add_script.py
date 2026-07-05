
import yaml

from app.watchlists.providers import InstrumentDraft
from scripts import watchlist_add


def test_watchlist_add_creates_yaml_file(monkeypatch, tmp_path):
    output = tmp_path / "watchlists.yaml"

    monkeypatch.setattr(
        watchlist_add,
        "resolve_instrument",
        lambda *_, **__: InstrumentDraft(
            market="CN",
            exchange="SSE",
            ticker="600519",
            company_name="贵州茅台",
            local_name="贵州茅台",
            aliases=["贵州茅台"],
            currency="CNY",
        ),
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "watchlist_add.py",
            "A股观察",
            "600519",
            "--priority",
            "high",
            "--holding",
            "--file",
            str(output),
        ],
    )

    watchlist_add.main()

    data = yaml.safe_load(output.read_text(encoding="utf-8"))
    item = data["watchlists"][0]["items"][0]
    assert data["watchlists"][0]["name"] == "A股观察"
    assert item["ticker"] == "600519"
    assert item["priority"] == "high"
    assert item["is_holding"] is True


def test_watchlist_add_updates_existing_item(monkeypatch, tmp_path):
    output = tmp_path / "watchlists.yaml"
    output.write_text(
        """
watchlists:
- name: A股观察
  items:
  - market: CN
    exchange: SSE
    ticker: '600519'
    company_name: 旧名称
    currency: CNY
    priority: medium
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        watchlist_add,
        "resolve_instrument",
        lambda *_, **__: InstrumentDraft(
            market="CN",
            exchange="SSE",
            ticker="600519",
            company_name="贵州茅台",
            currency="CNY",
        ),
    )
    monkeypatch.setattr(
        "sys.argv",
        ["watchlist_add.py", "A股观察", "600519", "--priority", "low", "--file", str(output)],
    )

    watchlist_add.main()

    data = yaml.safe_load(output.read_text(encoding="utf-8"))
    items = data["watchlists"][0]["items"]
    assert len(items) == 1
    assert items[0]["company_name"] == "贵州茅台"
    assert items[0]["priority"] == "low"


def test_watchlist_add_dry_run_does_not_write(monkeypatch, tmp_path):
    output = tmp_path / "watchlists.yaml"
    monkeypatch.setattr(
        watchlist_add,
        "resolve_instrument",
        lambda *_, **__: InstrumentDraft(
            market="US",
            exchange="NASDAQ",
            ticker="AAPL",
            company_name="Apple Inc.",
            currency="USD",
        ),
    )
    monkeypatch.setattr(
        "sys.argv",
        ["watchlist_add.py", "海外观察", "AAPL", "--dry-run", "--file", str(output)],
    )

    watchlist_add.main()

    assert not output.exists()
