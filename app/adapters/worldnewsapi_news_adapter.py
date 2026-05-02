from datetime import datetime, timezone
from typing import Any

import httpx

from app.adapters.base import BaseAdapter, RawDocument
from app.core.config import settings
from app.core.enums import SourceTier, SourceType


class WorldNewsAPITopNewsAdapter(BaseAdapter):
    source_name = "worldnewsapi_top_news"
    source_type = SourceType.NEWS.value
    source_tier = SourceTier.AGGREGATOR.value

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        source_country: str | None = None,
        language: str | None = None,
        headlines_only: bool | None = None,
        timeout_seconds: float | None = None,
        request_date: str | None = None,
    ):
        self.api_key = api_key if api_key is not None else settings.worldnewsapi_api_key
        self.base_url = (base_url or settings.worldnewsapi_base_url).rstrip("/")
        self.source_country = source_country or settings.worldnewsapi_source_country
        self.language = language or settings.worldnewsapi_language
        self.headlines_only = (
            headlines_only
            if headlines_only is not None
            else settings.worldnewsapi_headlines_only
        )
        self.timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else settings.worldnewsapi_timeout_seconds
        )
        self.request_date = request_date or datetime.now(timezone.utc).date().isoformat()

    def _build_params(self) -> dict[str, Any]:
        if not self.api_key:
            raise ValueError("worldnewsapi_api_key must be configured to fetch top news")

        return {
            "api-key": self.api_key,
            "source-country": self.source_country,
            "language": self.language,
            "date": self.request_date,
            "headlines-only": str(self.headlines_only).lower(),
        }

    def fetch(self) -> list[dict[str, Any]]:
        response = httpx.get(
            f"{self.base_url}/top-news",
            params=self._build_params(),
            timeout=self.timeout_seconds,
            follow_redirects=True,
        )
        response.raise_for_status()
        return [{"payload": response.json(), "request_date": self.request_date}]

    def parse(self, raw_data: list[dict[str, Any]]) -> list[RawDocument]:
        docs: list[RawDocument] = []
        for entry in raw_data:
            payload = entry.get("payload", {})
            request_date = entry.get("request_date", self.request_date)
            country = payload.get("country") or self.source_country
            language = payload.get("language") or self.language

            for cluster_index, cluster in enumerate(payload.get("top_news", []), start=1):
                articles = cluster.get("news", [])
                cluster_size = len(articles)

                for article in articles:
                    docs.append(
                        RawDocument(
                            title=(article.get("title") or "").strip(),
                            url=article.get("url"),
                            author=self._extract_author(article),
                            published_at=article.get("publish_date"),
                            raw_text=self._extract_raw_text(article),
                            language=language,
                            metadata={
                                "worldnewsapi_article_id": article.get("id"),
                                "summary": article.get("summary"),
                                "authors": article.get("authors"),
                                "image": article.get("image"),
                                "video": article.get("video"),
                                "cluster_index": cluster_index,
                                "cluster_size": cluster_size,
                                "source_country": country,
                                "request_date": request_date,
                                "headlines_only": self.headlines_only,
                            },
                        )
                    )
        return docs

    @staticmethod
    def _extract_author(article: dict[str, Any]) -> str | None:
        author = article.get("author")
        if isinstance(author, str) and author.strip():
            return author.strip()

        authors = article.get("authors")
        if isinstance(authors, list):
            for name in authors:
                if isinstance(name, str) and name.strip():
                    return name.strip()

        return None

    @staticmethod
    def _extract_raw_text(article: dict[str, Any]) -> str:
        for field in ("text", "summary"):
            value = article.get(field)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""
