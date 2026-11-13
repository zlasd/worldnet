from datetime import datetime, timedelta

from app.digests.config import parse_digest_task_config
from app.digests.runner import collect_digest_candidates
from app.models.digest import DigestItem, DigestLog
from app.models.normalized_event import NormalizedEvent
from app.models.source_document import SourceDocument
from app.pipelines.reclassify import reclassify_events
from tests.test_digest_runner import _add_event

START = datetime(2026, 11, 12)
END = START + timedelta(days=1)


def seed(session, event_id, title, when=START):
    _add_event(session, event_id=event_id, detected_at=when, raw_text="")
    event = session.get(NormalizedEvent, event_id)
    doc = session.get(SourceDocument, f"document-{event_id}")
    event.title = doc.title = title
    event.source_tier = doc.source_tier
    event.event_type = "management_change"
    session.flush()
    return event


def test_repair_is_bounded_dry_run_safe_idempotent_and_preserves_sent_history(session):
    departure = seed(session, "departure", "英伟达宣布CEO黄仁勋辞职 CFO出任临时CEO")
    interview = seed(session, "interview", "OpenTable CEO on dining trends")
    outside = seed(session, "outside", "Company CEO resigns", END)
    macro = seed(session, "macro", "Company CEO resigns")
    macro.event_type = "macro_data_release"
    session.add(DigestLog(digest_id="sent", digest_type="important_daily", window_start=START,
                          window_end=END, outlet_id="test", channel="email", title="old",
                          body="Original P2 digest", status="sent"))
    session.flush()
    session.add(DigestItem(digest_id="sent", event_id="departure", rank=1, priority="p2"))
    session.flush()
    preview = reclassify_events(session, since=START, until=END)
    assert preview["scanned"] == 2
    assert preview["changed"] == 2
    assert preview["after"] == {"p1": 1, "p3": 1}
    assert not session.dirty
    assert departure.severity == "medium"
    reclassify_events(session, since=START, until=END, apply=True)
    assert departure.severity == "high"
    assert interview.event_type == "unknown"
    assert interview.severity == "low"
    assert outside.severity == "medium"
    assert macro.event_type == "macro_data_release"
    assert session.query(DigestItem).one().priority == "p2"
    assert session.get(DigestLog, "sent").body == "Original P2 digest"
    assert reclassify_events(session, since=START, until=END, apply=True)["changed"] == 0


def test_corrected_departure_is_selected_before_candidate_limit_and_has_reason(session):
    seed(session, "departure", "英伟达宣布CEO黄仁勋辞职", START)
    seed(session, "interview", "OpenTable CEO on dining trends", START + timedelta(hours=1))
    reclassify_events(session, since=START, until=END, apply=True)
    candidates = collect_digest_candidates(session, window_start=START, window_end=END,
        config=parse_digest_task_config({"selection": {"max_candidates": 1}}))
    assert candidates[0].event_id == "departure"
    assert candidates[0].priority == "p1"
    assert "关键管理层离任" in candidates[0].selection_reason
    assert "媒体/其他来源" in candidates[0].selection_reason
