from app.adapters.factory import PIPELINE_SOURCE_CHOICES, build_adapters
from app.adapters.official_announcement_adapter import OfficialAnnouncementAdapter
from app.adapters.rss_news_adapter import RSSNewsAdapter
from app.adapters.rsshub_route_adapter import (
    CLSRssDepthAdapter,
    CLSRssTelegraphAdapter,
    RSSHubRouteAdapter,
    SSEDisclosureAdapter,
    SZSEListedNoticeAdapter,
)
from app.adapters.worldnewsapi_news_adapter import WorldNewsAPITopNewsAdapter

__all__ = [
    "CLSRssDepthAdapter",
    "CLSRssTelegraphAdapter",
    "OfficialAnnouncementAdapter",
    "PIPELINE_SOURCE_CHOICES",
    "RSSNewsAdapter",
    "RSSHubRouteAdapter",
    "SSEDisclosureAdapter",
    "SZSEListedNoticeAdapter",
    "WorldNewsAPITopNewsAdapter",
    "build_adapters",
]
