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
