"""Deterministic topic gates and ranking shared by LLM and fallback digests."""

from __future__ import annotations

import re
from datetime import timezone

from app.digests.types import DigestCandidate

TOPIC_KEYWORDS = {
    "economy": (
        "economy",
        "economic",
        "inflation",
        "interest rates",
        "central bank",
        "earnings",
        "revenue",
        "stocks",
        "markets",
        "market",
        "trade",
        "tariff",
        "fiscal",
        "monetary",
        "bonds",
        "investment",
        "bank",
        "oil",
        "business",
        "merger",
        "acquisition",
        "经济",
        "金融",
        "通胀",
        "央行",
        "利率",
        "财报",
        "业绩",
        "股市",
        "关税",
        "产业",
        "财政",
        "货币",
    ),
    "politics": (
        "politics",
        "political",
        "election",
        "parliament",
        "government",
        "president",
        "sanctions",
        "diplomacy",
        "geopolitical",
        "ceasefire",
        "war",
        "legislation",
        "政治",
        "选举",
        "政府",
        "总统",
        "议会",
        "制裁",
        "外交",
        "地缘",
        "停火",
        "战争",
        "立法",
    ),
}
OFF_TOPIC_KEYWORDS = (
    "sports",
    "entertainment",
    "lifestyle",
    "travel guide",
    "product review",
    "new iphone",
    "new smartphone",
    "football",
    "soccer",
    "basketball",
    "world cup",
    "celebrity",
    "film review",
    "movie review",
    "fashion",
    "recipe",
    "horoscope",
    "smartphone review",
    "足球",
    "篮球",
    "世界杯",
    "娱乐",
    "明星",
    "影评",
    "穿搭",
    "食谱",
    "星座",
    "手机评测",
)


def contains_keyword(text: str, keyword: str) -> bool:
    keyword = keyword.strip().casefold()
    if not keyword:
        return False
    if keyword.isascii():
        return re.search(r"(?<!\w)" + re.escape(keyword) + r"(?!\w)", text.casefold()) is not None
    return keyword in text.casefold()


def matching_topics(title: str, text: str, source_topic: str | None) -> set[str]:
    combined = f"{title} {text}"
    # Feed categories provide a useful fallback but must not override an
    # explicitly off-topic headline (mixed-topic feeds are common).
    if any(contains_keyword(title, word) for word in OFF_TOPIC_KEYWORDS):
        return set()
    topics = {
        topic
        for topic, words in TOPIC_KEYWORDS.items()
        if any(contains_keyword(combined, word) for word in words)
    }
    if isinstance(source_topic, str) and source_topic in TOPIC_KEYWORDS:
        topics.add(source_topic)
    return topics


def candidate_sort_key(candidate: DigestCandidate) -> tuple:
    timestamp = candidate.event_time or candidate.detected_at
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return (
        {"p1": 0, "p2": 1, "p3": 2}.get(candidate.priority, 3),
        not candidate.watchlist_match,
        {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(candidate.severity, 4),
        -timestamp.timestamp(),
        candidate.event_id,
    )
