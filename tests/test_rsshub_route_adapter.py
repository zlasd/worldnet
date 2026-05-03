from app.adapters.factory import build_adapters
from app.adapters.rsshub_route_adapter import RSSHubRouteAdapter
from app.core.config import settings


def test_rsshub_route_adapter_builds_feed_url_and_metadata():
    adapter = RSSHubRouteAdapter(
        route_path="cls/telegraph",
        source_name="rsshub_cls_telegraph",
        base_url="https://rsshub.example.com",
        metadata={"upstream_source": "cls"},
    )

    docs = adapter.parse(
        [
            {
                "xml": """
                <rss version="2.0">
                  <channel>
                    <item>
                      <title>财联社电报</title>
                      <link>https://example.com/telegraph</link>
                      <description>市场快讯内容</description>
                      <pubDate>Wed, 01 May 2024 10:00:00 GMT</pubDate>
                    </item>
                  </channel>
                </rss>
                """
            }
        ]
    )

    assert adapter.feed_url == "https://rsshub.example.com/cls/telegraph"
    assert docs[0].metadata == {
        "feed_url": "https://rsshub.example.com/cls/telegraph",
        "rsshub_base_url": "https://rsshub.example.com",
        "rsshub_path": "/cls/telegraph",
        "rsshub_route": "cls/telegraph",
        "upstream_source": "cls",
    }


def test_build_adapters_all_respects_rsshub_enable_flags(monkeypatch):
    monkeypatch.setattr(settings, "rsshub_cls_telegraph_enabled", False)
    monkeypatch.setattr(settings, "rsshub_cls_depth_enabled", True)

    adapters = build_adapters("all")
    source_names = [adapter.source_name for adapter in adapters]

    assert "rsshub_cls_telegraph" not in source_names
    assert "rsshub_cls_depth" in source_names


def test_build_adapters_returns_explicit_rsshub_source_even_if_disabled(monkeypatch):
    monkeypatch.setattr(settings, "rsshub_cls_telegraph_enabled", False)

    adapter = build_adapters("rsshub_cls_telegraph")[0]

    assert adapter.source_name == "rsshub_cls_telegraph"
