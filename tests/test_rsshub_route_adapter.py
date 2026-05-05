from app.adapters.factory import build_adapters
from app.adapters.rsshub_route_adapter import (
    RSSHubRouteAdapter,
    build_rsshub_access_code,
    build_rsshub_feed_url,
    build_rsshub_route_path,
)
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
        "rsshub_protected": False,
        "upstream_source": "cls",
    }


def test_build_adapters_all_respects_rsshub_enable_flags(monkeypatch):
    monkeypatch.setattr(settings, "rsshub_cls_telegraph_enabled", False)
    monkeypatch.setattr(settings, "rsshub_cls_depth_enabled", True)
    monkeypatch.setattr(settings, "worldnewsapi_enabled", False)

    adapters = build_adapters("all")
    source_names = [adapter.source_name for adapter in adapters]

    assert "rsshub_cls_telegraph" not in source_names
    assert "rsshub_cls_depth" in source_names


def test_build_adapters_returns_explicit_rsshub_source_even_if_disabled(monkeypatch):
    monkeypatch.setattr(settings, "rsshub_cls_telegraph_enabled", False)

    adapter = build_adapters("rsshub_cls_telegraph")[0]

    assert adapter.source_name == "rsshub_cls_telegraph"


def test_build_rsshub_access_code_uses_route_plus_key():
    code = build_rsshub_access_code("cls/telegraph", "ILoveRSSHub")

    assert code == "94f910a8d81501b3693ee6f6880305fb"


def test_build_rsshub_feed_url_uses_code_when_access_key_is_configured():
    feed_url = build_rsshub_feed_url(
        base_url="https://rsshub.example.com",
        route_path="cls/telegraph",
        access_key="ILoveRSSHub",
    )

    assert (
        feed_url
        == "https://rsshub.example.com/cls/telegraph?code=94f910a8d81501b3693ee6f6880305fb"
    )


def test_build_rsshub_route_path_appends_route_params_in_order():
    route_path = build_rsshub_route_path(
        "sse/disclosure",
        {
            "productId": "600000",
            "beginDate": "2024-01-01",
            "endDate": "2024-01-31",
        },
    )

    assert route_path == "sse/disclosure/productId=600000&beginDate=2024-01-01&endDate=2024-01-31"


def test_build_adapters_supports_parameterized_exchange_routes():
    sse_adapter = build_adapters(
        "rsshub_sse_disclosure",
        {
            "product_id": "600000",
            "company_name": "浦发银行",
            "local_name": "浦发银行",
        },
    )[0]
    szse_adapter = build_adapters(
        "rsshub_szse_listed_notice",
        {
            "stock": "000001",
            "company_name": "平安银行",
            "local_name": "平安银行",
        },
    )[0]

    assert sse_adapter.source_name == "rsshub_sse_disclosure"
    assert sse_adapter.feed_url == "http://localhost:1200/sse/disclosure/productId=600000"
    assert szse_adapter.source_name == "rsshub_szse_listed_notice"
    assert szse_adapter.feed_url == "http://localhost:1200/szse/disclosure/listed/notice/stock=000001"
