from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from app.adapters.base import BaseAdapter
from app.adapters.official_announcement_adapter import OfficialAnnouncementAdapter
from app.adapters.rsshub_route_adapter import (
    CLSRssDepthAdapter,
    CLSRssTelegraphAdapter,
    SSEDisclosureAdapter,
    SZSEListedNoticeAdapter,
)
from app.adapters.worldnewsapi_news_adapter import WorldNewsAPITopNewsAdapter
from app.core.config import settings

DEFAULT_SOURCE = "official_announcement"


@dataclass(frozen=True)
class SourceSpec:
    builder: Callable[..., BaseAdapter]
    enabled: Callable[[], bool] | None = None
    include_in_all: bool = True


SUPPORTED_SOURCES: dict[str, SourceSpec] = {
    "official_announcement": SourceSpec(builder=OfficialAnnouncementAdapter),
    "rsshub_cls_telegraph": SourceSpec(
        builder=CLSRssTelegraphAdapter,
        enabled=lambda: settings.rsshub_cls_telegraph_enabled,
    ),
    "rsshub_cls_depth": SourceSpec(
        builder=CLSRssDepthAdapter,
        enabled=lambda: settings.rsshub_cls_depth_enabled,
    ),
    "rsshub_sse_disclosure": SourceSpec(
        builder=SSEDisclosureAdapter,
        include_in_all=False,
    ),
    "rsshub_szse_listed_notice": SourceSpec(
        builder=SZSEListedNoticeAdapter,
        include_in_all=False,
    ),
    "worldnewsapi_top_news": SourceSpec(
        builder=WorldNewsAPITopNewsAdapter,
        enabled=lambda: settings.worldnewsapi_enabled,
    ),
}

PIPELINE_SOURCE_CHOICES = tuple([*SUPPORTED_SOURCES.keys(), "all"])


def is_source_enabled(source: str) -> bool:
    source_spec = SUPPORTED_SOURCES[source]
    return source_spec.enabled() if source_spec.enabled else True


def build_adapters(
    source: str = DEFAULT_SOURCE,
    source_config: dict[str, Any] | None = None,
) -> list[BaseAdapter]:
    if source == "all":
        if source_config:
            raise ValueError("source_config is not supported when source='all'.")
        return [
            source_spec.builder()
            for source_name, source_spec in SUPPORTED_SOURCES.items()
            if source_spec.include_in_all and is_source_enabled(source_name)
        ]

    source_spec = SUPPORTED_SOURCES.get(source)
    if source_spec is None:
        options = ", ".join(PIPELINE_SOURCE_CHOICES)
        raise ValueError(f"Unsupported source '{source}'. Expected one of: {options}")

    return [source_spec.builder(**(source_config or {}))]
