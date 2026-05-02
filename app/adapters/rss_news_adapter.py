import httpx
from bs4 import BeautifulSoup

from app.adapters.base import BaseAdapter, RawDocument


class RSSNewsAdapter(BaseAdapter):
    source_name = "rss_news"
    source_type = "news"
    source_tier = "secondary_media"

    def __init__(self, feed_url: str, source_name: str | None = None):
        self.feed_url = feed_url
        if source_name:
            self.source_name = source_name

    def fetch(self) -> list[dict]:
        try:
            resp = httpx.get(self.feed_url, timeout=30, follow_redirects=True)
            resp.raise_for_status()
            return [{"xml": resp.text}]
        except Exception:
            return []

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
                docs.append(
                    RawDocument(
                        title=title.text.strip() if title else "",
                        url=link.text.strip() if link else None,
                        author=author.text.strip() if author else None,
                        published_at=pub_date.text.strip() if pub_date else None,
                        raw_text=desc.text.strip() if desc else "",
                        language="en",
                        metadata={"feed_url": self.feed_url},
                    )
                )
        return docs
