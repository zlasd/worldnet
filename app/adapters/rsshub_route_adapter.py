from typing import Any

from app.adapters.rss_news_adapter import RSSNewsAdapter
from app.core.config import settings


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
        route_metadata = {
            "rsshub_base_url": normalized_base_url,
            "rsshub_path": f"/{normalized_path}",
            "rsshub_route": normalized_path,
            **(metadata or {}),
        }
        super().__init__(
            feed_url=f"{normalized_base_url}/{normalized_path}",
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
