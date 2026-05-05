import hashlib
from typing import Any
from urllib.parse import urlencode

from app.adapters.rss_news_adapter import RSSNewsAdapter
from app.core.config import settings


def build_rsshub_access_code(route_path: str, access_key: str) -> str:
    normalized_path = f"/{route_path.strip('/')}"
    return hashlib.md5(f"{normalized_path}{access_key}".encode("utf-8")).hexdigest()


def build_rsshub_feed_url(base_url: str, route_path: str, access_key: str | None = None) -> str:
    normalized_base_url = base_url.rstrip("/")
    normalized_path = route_path.strip("/")
    feed_url = f"{normalized_base_url}/{normalized_path}"
    if access_key:
        query = urlencode({"code": build_rsshub_access_code(normalized_path, access_key)})
        return f"{feed_url}?{query}"
    return feed_url


def build_rsshub_route_path(base_route: str, route_params: dict[str, str | None] | None = None) -> str:
    normalized_base_route = base_route.strip("/")
    if not route_params:
        return normalized_base_route

    filtered_params = {key: value for key, value in route_params.items() if value}
    if not filtered_params:
        return normalized_base_route

    return f"{normalized_base_route}/{'&'.join(f'{key}={value}' for key, value in filtered_params.items())}"


def build_instrument_entity_hint(
    ticker: str | None,
    company_name: str | None,
    local_name: str | None = None,
) -> str | None:
    parts = [part.strip() for part in [ticker, company_name, local_name] if part and part.strip()]
    if not parts:
        return None
    return " ".join(dict.fromkeys(parts))


class RSSHubRouteAdapter(RSSNewsAdapter):
    def __init__(
        self,
        route_path: str,
        source_name: str,
        source_type: str = "news",
        source_tier: str = "secondary_media",
        language: str = "zh",
        base_url: str | None = None,
        timeout_seconds: float | None = None,
        metadata: dict[str, Any] | None = None,
        entity_hint_text: str | None = None,
    ):
        normalized_path = route_path.strip("/")
        normalized_base_url = (base_url or settings.rsshub_base_url).rstrip("/")
        access_key = settings.rsshub_access_key
        feed_url = build_rsshub_feed_url(
            base_url=normalized_base_url,
            route_path=normalized_path,
            access_key=access_key,
        )
        route_metadata = {
            "rsshub_base_url": normalized_base_url,
            "rsshub_path": f"/{normalized_path}",
            "rsshub_route": normalized_path,
            "rsshub_protected": bool(access_key),
            **(metadata or {}),
        }
        super().__init__(
            feed_url=feed_url,
            source_name=source_name,
            source_type=source_type,
            source_tier=source_tier,
            language=language,
            metadata=route_metadata,
            entity_hint_text=entity_hint_text,
            timeout_seconds=timeout_seconds
            if timeout_seconds is not None
            else settings.rsshub_timeout_seconds,
        )


class CLSRssTelegraphAdapter(RSSHubRouteAdapter):
    def __init__(self):
        super().__init__(
            route_path="cls/telegraph",
            source_name="rsshub_cls_telegraph",
            metadata={
                "upstream_source": "cls",
                "route_kind": "telegraph",
                "poll_interval_minutes": settings.rsshub_cls_telegraph_poll_interval_minutes,
            },
        )


class CLSRssDepthAdapter(RSSHubRouteAdapter):
    def __init__(self):
        super().__init__(
            route_path="cls/depth",
            source_name="rsshub_cls_depth",
            metadata={
                "upstream_source": "cls",
                "route_kind": "depth",
                "poll_interval_minutes": settings.rsshub_cls_depth_poll_interval_minutes,
            },
        )


class SZSEListedNoticeAdapter(RSSHubRouteAdapter):
    def __init__(
        self,
        stock: str,
        begin_date: str | None = None,
        end_date: str | None = None,
        company_name: str | None = None,
        local_name: str | None = None,
    ):
        route_path = build_rsshub_route_path(
            "szse/disclosure/listed/notice",
            {
                "stock": stock,
                "beginDate": begin_date,
                "endDate": end_date,
            },
        )
        super().__init__(
            route_path=route_path,
            source_name="rsshub_szse_listed_notice",
            source_type="official_announcement",
            source_tier="exchange",
            metadata={
                "upstream_source": "szse",
                "route_kind": "listed_notice",
                "stock": stock,
            },
            entity_hint_text=build_instrument_entity_hint(stock, company_name, local_name),
        )


class SSEDisclosureAdapter(RSSHubRouteAdapter):
    def __init__(
        self,
        product_id: str,
        begin_date: str | None = None,
        end_date: str | None = None,
        company_name: str | None = None,
        local_name: str | None = None,
    ):
        route_path = build_rsshub_route_path(
            "sse/disclosure",
            {
                "productId": product_id,
                "beginDate": begin_date,
                "endDate": end_date,
            },
        )
        super().__init__(
            route_path=route_path,
            source_name="rsshub_sse_disclosure",
            source_type="official_announcement",
            source_tier="exchange",
            metadata={
                "upstream_source": "sse",
                "route_kind": "disclosure",
                "product_id": product_id,
            },
            entity_hint_text=build_instrument_entity_hint(product_id, company_name, local_name),
        )
