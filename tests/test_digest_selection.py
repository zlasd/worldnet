import json
from dataclasses import replace
from datetime import datetime, timedelta

from app.digests.config import parse_digest_task_config
from app.digests.dispatcher import DigestDispatcher
from app.digests.llm import select_digest_items, validate_digest_output
from app.digests.runner import collect_digest_candidates, run_important_daily_digest
from app.digests.types import DigestMessagePayload, safe_source_url
from app.models.digest import DigestLog
from app.models.instrument import Instrument
from app.models.normalized_event import NormalizedEvent
from app.models.source_document import SourceDocument
from app.models.watchlist import Watchlist, WatchlistItem
from tests.test_digest_llm import FakeDigestClient, _candidate, _valid_output
from tests.test_digest_runner import _add_event

START = datetime(2026, 7, 4)
END = START + timedelta(days=1)


def collect(session, **selection):
    return collect_digest_candidates(
        session,
        window_start=START,
        window_end=END,
        config=parse_digest_task_config({"selection": selection}),
    )


def test_rank_before_candidate_limit_keeps_older_important_news(session):
    _add_event(session, event_id="important", detected_at=START + timedelta(hours=1))
    for index in range(5):
        _add_event(
            session,
            event_id=f"noise-{index}",
            detected_at=START + timedelta(hours=2 + index),
            severity="low",
            actionability="digest_only",
        )
    assert [row.event_id for row in collect(session, max_candidates=1)] == ["important"]


def test_topic_filter_applies_without_llm_and_overrides_mixed_feed_label(session):
    for event_id, title in (
        ("politics", "Government announces election"),
        ("economy", "央行宣布调整利率"),
        ("sport", "Football world cup final"),
        ("custom-excluded", "Government announces election rumor"),
    ):
        _add_event(session, event_id=event_id, detected_at=START + timedelta(hours=1), raw_text="")
        session.get(NormalizedEvent, event_id).title = title
        session.get(SourceDocument, f"document-{event_id}").metadata_ = '{"topic":"economy"}'
    session.flush()
    candidates = collect(
        session, allowed_topics=["economy", "politics"], excluded_keywords=["rumor"]
    )
    assert {c.event_id for c in candidates} == {"politics", "economy"}
    result = select_digest_items(candidates, parse_digest_task_config({"llm": {"enabled": False}}))
    assert {c.event_id for c in result.items} == {"politics", "economy"}
    assert all("主题：" in item.selection_reason for item in result.items)


def test_same_filtered_pool_used_when_llm_fails(session):
    _add_event(session, event_id="policy", detected_at=START, raw_text="government election")
    _add_event(session, event_id="sports", detected_at=START, raw_text="football")
    session.get(NormalizedEvent, "sports").title = "Football match"
    session.flush()
    client = FakeDigestClient(["__raise__"])
    result = run_important_daily_digest(
        session,
        {"selection": {"allowed_topics": ["politics"]}, "llm": {"max_retries": 0}},
        now=END,
        dispatcher=DigestDispatcher([]),
        llm_client=client,
    )
    assert result["used_llm"] is False
    assert result["items"] == 1
    prompt = client.messages[0][1]["content"]
    assert '"event_id": "policy"' in prompt
    assert '"event_id": "sports"' not in prompt


def test_watchlist_ranking_includes_related_active_instruments(session):
    instrument = Instrument(
        instrument_id="held",
        market="US",
        ticker="TEST",
        exchange="NASDAQ",
        company_name="Test",
        currency="USD",
    )
    watchlist = Watchlist(watchlist_id="list", name="Active")
    session.add_all([instrument, watchlist])
    session.flush()
    item = WatchlistItem(watchlist_id="list", instrument_id="held", is_active=True)
    session.add(item)
    _add_event(session, event_id="related", detected_at=START)
    _add_event(session, event_id="other", detected_at=START + timedelta(hours=1))
    session.get(NormalizedEvent, "related").related_instrument_ids = '["held"]'
    session.flush()
    assert collect(session)[0].event_id == "related"
    assert [c.event_id for c in collect(session, include_watchlist_only=True)] == ["related"]
    item.is_active = False
    session.flush()
    assert collect(session, include_watchlist_only=True) == []


def test_provenance_is_from_candidate_even_if_llm_forges_it():
    candidate = replace(
        _candidate(),
        source_url="https://example.com/original?q=a&b=c",
        published_at=START,
        selection_reason="关联关注标的",
    )
    content = json.loads(_valid_output())
    content["items"][0]["source_url"] = "https://forged.example.com"
    result = validate_digest_output(json.dumps(content), [candidate], 10)
    item = result.items[0]
    assert item.source_url == candidate.source_url
    payload = DigestMessagePayload(
        title="日报",
        body="",
        window_start=START,
        window_end=END,
        summary=result.summary,
        items=result.items,
    )
    assert "https://example.com/original" in payload.weixin_body
    assert 'href="https://example.com/original?q=a&amp;b=c"' in payload.html_body
    assert "2026-07-04T00:00Z" in payload.html_body
    assert "关联关注标的" in payload.html_body
    assert "forged" not in payload.html_body


def test_unsafe_links_are_never_rendered():
    for url in (
        "javascript:alert(1)",
        "data:text/html,hi",
        "https://user:secret@example.com",
        "https://example.com\nInjected",
        "http://[invalid",
    ):
        assert safe_source_url(url) is None


def test_plain_digest_persists_source_evidence(session):
    _add_event(session, detected_at=START)
    doc = session.get(SourceDocument, "document-event-1")
    doc.url, doc.published_at = "https://example.com/article", START
    session.flush()
    run_important_daily_digest(
        session, {"llm": {"enabled": False}}, now=END, dispatcher=DigestDispatcher([])
    )
    body = session.query(DigestLog).one().body
    assert "原文：https://example.com/article" in body
    assert "来源：rsshub_cls_telegraph" in body
    assert "发布：2026-07-04T00:00Z" in body
    assert "入选依据：" in body
