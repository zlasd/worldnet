from app.adapters.base import BaseAdapter
from app.adapters.official_announcement_adapter import OfficialAnnouncementAdapter
from app.adapters.worldnewsapi_news_adapter import WorldNewsAPITopNewsAdapter

DEFAULT_SOURCE = "official_announcement"

SUPPORTED_SOURCES: dict[str, type[BaseAdapter]] = {
    # "official_announcement": OfficialAnnouncementAdapter,
    "worldnewsapi_top_news": WorldNewsAPITopNewsAdapter,
}

PIPELINE_SOURCE_CHOICES = tuple([*SUPPORTED_SOURCES.keys(), "all"])


def build_adapters(source: str = DEFAULT_SOURCE) -> list[BaseAdapter]:
    if source == "all":
        return [adapter_class() for adapter_class in SUPPORTED_SOURCES.values()]

    adapter_class = SUPPORTED_SOURCES.get(source)
    if adapter_class is None:
        options = ", ".join(PIPELINE_SOURCE_CHOICES)
        raise ValueError(f"Unsupported source '{source}'. Expected one of: {options}")

    return [adapter_class()]
