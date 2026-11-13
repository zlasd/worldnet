from app.core.enums import EventType, Sentiment
from app.rules.keyword_rules import detect_event_type, detect_sentiment
from app.rules.text_rules import management_change_kind


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


def test_executive_title_alone_is_not_a_management_change():
    for title in (
        "Oil Supertanker Squeeze Is Crimping US Crude Exports, Texas Port CEO Says",
        "OpenTable CEO on 2027 Dining Trends Report",
        "Cooperation on fiscal policy expands",
    ):
        assert detect_event_type(title)[0] != EventType.MANAGEMENT_CHANGE


def test_english_words_and_html_attributes_do_not_create_false_events():
    assert detect_event_type("Watch the final seconds", "<img src='https://example.com/EPS/CEO.png'>")[0] == EventType.UNKNOWN
    assert detect_event_type("The project takes new steps")[0] == EventType.UNKNOWN
    assert detect_event_type("Leaders suspended the talks")[0] != EventType.TRADING_HALT
    assert detect_event_type("美企EPS超预期")[0] == EventType.EARNINGS_RELEASE


def test_explicit_chinese_and_english_executive_departures():
    for title in (
        "英伟达宣布CEO黄仁勋辞职 CFO科莱特·克雷斯出任临时CEO",
        "黄仁勋辞去总裁、首席执行官及董事会成员职务，即刻生效",
        "Nvidia CEO Jensen Huang quits",
        "The chief executive steps down",
    ):
        assert detect_event_type(title)[0] == EventType.MANAGEMENT_CHANGE
        assert management_change_kind(title) == "departure"


def test_denial_rumor_and_unrelated_actions_do_not_confirm_departure():
    assert management_change_kind("CEO denies resignation rumors", "The CEO resigned, a rumor said.") is None
    assert management_change_kind("公司否认CEO辞职", "传闻CEO已辞职") is None
    assert management_change_kind("Nvidia preparing to oust CEO Jensen Huang") == "proposed"
    assert management_change_kind("公司或将解聘CEO") == "proposed"
    assert management_change_kind("CEO interview", "The minister resigned. The CEO discusses earnings.") is None
    assert management_change_kind("Pivotal Advisors CEO: Investors Should See AI as Part of Portfolio", "Nvidia CEO Jensen Huang resigned today.") is None
    assert management_change_kind("Daily Podcast: Nvidia Strategy Reset", "Nvidia CEO Jensen Huang resigned today.") is None
    assert management_change_kind("Jensen Huang has resigned", "Nvidia CEO has left the company.") == "departure"


def test_headline_subject_beats_incidental_body_terms():
    assert detect_event_type(
        "Company announces share repurchase", "The CEO discusses revenue, EPS and financial results."
    )[0] == EventType.BUYBACK
    assert detect_event_type("公司筹划收购股权，股票明起停牌")[0] == EventType.TRADING_HALT
