from app.adapters.base import BaseAdapter
from app.adapters.official_announcement_adapter import OfficialAnnouncementAdapter
from app.adapters.rsshub_route_adapter import CLSRssDepthAdapter, CLSRssTelegraphAdapter
from app.adapters.worldnewsapi_news_adapter import WorldNewsAPITopNewsAdapter
from app.core.config import settings

DEFAULT_SOURCE = "official_announcement"

SUPPORTED_SOURCES: dict[str, type[BaseAdapter]] = {
    "official_announcement": OfficialAnnouncementAdapter,
    "rsshub_cls_telegraph": CLSRssTelegraphAdapter,
    "rsshub_cls_depth": CLSRssDepthAdapter,
    "worldnewsapi_top_news": WorldNewsAPITopNewsAdapter,
}

PIPELINE_SOURCE_CHOICES = tuple([*SUPPORTED_SOURCES.keys(), "all"])
ENABLED_SOURCE_FLAGS = {
    "rsshub_cls_telegraph": lambda: settings.rsshub_cls_telegraph_enabled,
    "rsshub_cls_depth": lambda: settings.rsshub_cls_depth_enabled,
}


def is_source_enabled(source: str) -> bool:
    enabled_flag = ENABLED_SOURCE_FLAGS.get(source)
    return enabled_flag() if enabled_flag else True


def build_adapters(source: str = DEFAULT_SOURCE) -> list[BaseAdapter]:
    if source == "all":
        return [
            adapter_class()
            for source_name, adapter_class in SUPPORTED_SOURCES.items()
            if is_source_enabled(source_name)
        ]

    adapter_class = SUPPORTED_SOURCES.get(source)
    if adapter_class is None:
        options = ", ".join(PIPELINE_SOURCE_CHOICES)
        raise ValueError(f"Unsupported source '{source}'. Expected one of: {options}")

    return [adapter_class()]
