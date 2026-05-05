from typing import Any

import httpx
from bs4 import BeautifulSoup

from app.adapters.base import BaseAdapter, RawDocument


class RSSNewsAdapter(BaseAdapter):
    source_name = "rss_news"
    source_type = "news"
    source_tier = "secondary_media"

    def __init__(
        self,
        feed_url: str,
        source_name: str | None = None,
        source_type: str | None = None,
        source_tier: str | None = None,
        language: str = "en",
        metadata: dict[str, Any] | None = None,
        entity_hint_text: str | None = None,
        timeout_seconds: float = 30.0,
    ):
        self.feed_url = feed_url
        if source_name:
            self.source_name = source_name
        if source_type:
            self.source_type = source_type
        if source_tier:
            self.source_tier = source_tier
        self.language = language
        self.metadata = metadata.copy() if metadata else {}
        self.entity_hint_text = entity_hint_text.strip() if entity_hint_text else None
        self.timeout_seconds = timeout_seconds

    def fetch(self) -> list[dict]:
        resp = httpx.get(self.feed_url, timeout=self.timeout_seconds, follow_redirects=True)
        resp.raise_for_status()
        return [{"xml": resp.text}]

    def parse(self, raw_data: list[dict]) -> list[RawDocument]:
        docs = []
        for item in raw_data:
            xml = item.get("xml", "")
            soup = BeautifulSoup(xml, "xml")
            for entry in soup.find_all("item"):
                title = entry.find("title")
                link = entry.find("link")
                desc = entry.find("description")
                pub_date = entry.find("pubDate")
                author = entry.find("author") or entry.find("dc:creator")
                raw_text = desc.text.strip() if desc else ""
                if self.entity_hint_text:
                    raw_text = f"{raw_text}\n{self.entity_hint_text}".strip()
                docs.append(
                    RawDocument(
                        title=title.text.strip() if title else "",
                        url=link.text.strip() if link else None,
                        author=author.text.strip() if author else None,
                        published_at=pub_date.text.strip() if pub_date else None,
                        raw_text=raw_text,
                        language=self.language,
                        metadata={"feed_url": self.feed_url, **self.metadata},
                    )
                )
        return docs
