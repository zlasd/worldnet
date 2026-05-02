from app.adapters.base import BaseAdapter, RawDocument

SAMPLE_ANNOUNCEMENTS = [
    {
        "title": "Apple Inc. Reports Second Quarter Results",
        "url": "https://investor.apple.com/news/press-releases/2024/q2-results",
        "author": "Apple Inc.",
        "published_at": "2024-05-02T20:30:00Z",
        "text": "Apple today announced financial results for its fiscal 2024 second quarter ended March 30, 2024. The Company posted quarterly revenue of $90.8 billion, down 4 percent year over year, and quarterly earnings per share of $1.53.",
        "language": "en",
    },
    {
        "title": "腾讯控股有限公司宣布回购计划",
        "url": "https://www.tencent.com/ir/ann/2024",
        "author": "腾讯控股",
        "published_at": "2024-05-01T09:00:00Z",
        "text": "腾讯控股有限公司宣布将在未来12个月内回购不超过1000亿港元的股份。",
        "language": "zh",
    },
    {
        "title": "贵州茅台公告：大股东减持计划",
        "url": "https://www.moutai.com.cn/ir/2024/reduce",
        "author": "贵州茅台",
        "published_at": "2024-04-30T16:00:00Z",
        "text": "贵州茅台酒股份有限公司第一大股东拟减持不超过1%的公司股份。",
        "language": "zh",
    },
]


class OfficialAnnouncementAdapter(BaseAdapter):
    source_name = "official_announcement"
    source_type = "exchange_announcement"
    source_tier = "official"

    def fetch(self) -> list[dict]:
        return SAMPLE_ANNOUNCEMENTS

    def parse(self, raw_data: list[dict]) -> list[RawDocument]:
        docs = []
        for item in raw_data:
            docs.append(
                RawDocument(
                    title=item["title"],
                    url=item.get("url"),
                    author=item.get("author"),
                    published_at=item.get("published_at"),
                    raw_text=item.get("text", ""),
                    language=item.get("language", "en"),
                    metadata={"adapter": "official_announcement"},
                )
            )
        return docs
