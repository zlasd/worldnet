
from app.core.enums import EventType, Sentiment
from app.rules.keyword_rules import detect_event_type, detect_sentiment


def test_detect_earnings_release():
    event_type, _ = detect_event_type("Apple Inc. Reports Second Quarter Results", "Revenue was $90.8 billion")
    assert event_type == EventType.EARNINGS_RELEASE


def test_detect_buyback():
    event_type, _ = detect_event_type("Tencent announces share repurchase program", "回购计划")
    assert event_type == EventType.BUYBACK


def test_detect_major_holder_change():
    event_type, _ = detect_event_type("贵州茅台大股东减持计划公告", "拟减持不超过1%")
    assert event_type == EventType.MAJOR_HOLDER_CHANGE


def test_detect_unknown():
    event_type, _ = detect_event_type("Miscellaneous unrelated text here", "nothing relevant")
    assert event_type == EventType.UNKNOWN


def test_detect_sentiment_positive():
    sentiment = detect_sentiment("Company beats earnings expectations with record revenue")
    assert sentiment == Sentiment.POSITIVE


def test_detect_sentiment_negative():
    sentiment = detect_sentiment("Company misses earnings, stock halted pending investigation")
    assert sentiment == Sentiment.NEGATIVE


def test_detect_sentiment_mixed():
    sentiment = detect_sentiment("Company beats revenue but issues profit warning for next quarter")
    assert sentiment == Sentiment.MIXED


def test_detect_sentiment_neutral():
    sentiment = detect_sentiment("Company announces annual general meeting date")
    assert sentiment == Sentiment.NEUTRAL
