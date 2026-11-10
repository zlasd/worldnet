from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy import event as sa_event
from sqlalchemy.orm import Session

from app.db.base import Base
from app.digests.dispatcher import DigestDispatcher
from app.digests.runner import run_important_daily_digest
from app.macro_calendar.service import run_calendar_digest
from app.macro_calendar.types import CalendarRelease
from app.macro_data.service import run_data_digest
from app.macro_data.types import Reading, Release
from app.models.digest import DigestItem, DigestLog
from app.models.normalized_event import NormalizedEvent
from app.models.source_document import SourceDocument
from app.notifications.base import NotificationResult
from app.sync.transfer import build_batch, import_batch

NOW = (datetime.now(timezone.utc) + timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0)


class Notifier:
    channel = "email"

    def __init__(self, outlet_id="test", ok=True):
        self.outlet_id, self.ok, self.sent = outlet_id, ok, []

    def send(self, payload):
        self.sent.append(payload)
        return NotificationResult(ok=self.ok, error=None if self.ok else "temporary failure")


class Client:
    warnings = []

    def fetch(self, provider, now):
        if provider == "bls":
            return [Release(provider="bls", country="US", group="cpi", period="2026-10",
                            title="美国 CPI", source_url="https://www.bls.gov/cpi/",
                            readings=[Reading(series_id="US.test", name="CPI 同比", period="2026-10", value="1.23", unit="%")])]
        return [CalendarRelease(provider="bea", key="gdp", title="美国 GDP 发布预告", country="US",
                                release_date=NOW.date() + timedelta(days=7), timezone="UTC",
                                source_url="https://www.bea.gov/news/schedule")]


def collect(session, notifier=None):
    kwargs = {"now": NOW, "client": Client(), "dispatcher": DigestDispatcher([notifier] if notifier else [])}
    run_data_digest(session, {"providers": ["bls"]}, **kwargs)
    run_calendar_digest(session, {"providers": ["bea"]}, **kwargs)


def daily(session, notifiers, now, **config):
    return run_important_daily_digest(session, {"llm": {"enabled": False}, **config},
                                      dispatcher=DigestDispatcher(notifiers), now=now)


def test_collectors_default_to_no_delivery_and_daily_merges_without_llm_or_news_cap(session, monkeypatch):
    notifier = Notifier()
    collect(session, notifier)
    assert notifier.sent == []
    assert session.query(DigestLog).filter_by(status="skipped", outlet_id="none").count() == 2
    assert session.query(DigestItem).count() == 2
    session.add(SourceDocument(document_id="news", source_name="news", source_type="rss", source_tier="official", title="经济新闻"))
    session.add(NormalizedEvent(document_id="news", event_type="policy_change", title="经济新闻", summary="新闻摘要",
                                severity="high", sentiment="neutral", actionability="monitor", source_tier="official",
                                detected_at=NOW.replace(tzinfo=None)))
    session.flush()
    from app.digests import runner

    original = runner.select_digest_items

    def select(candidates, *args, **kwargs):
        assert all(c.event_type == "policy_change" for c in candidates)
        return original(candidates, *args, **kwargs)

    monkeypatch.setattr(runner, "select_digest_items", select)
    result = daily(session, [notifier], NOW + timedelta(hours=1), selection={"max_candidates": 1, "max_items": 1})
    assert result["items"] == 3 and result["macro_items"] == 2
    assert len(notifier.sent) == 1
    payload = notifier.sent[0]
    assert len(payload.items) == 3 and "1.23 %" in payload.message_body and "提前 7 天" in payload.html_body
    assert [item.rank for item in payload.items] == [1, 2, 3]
    daily(session, [notifier], NOW + timedelta(days=1))
    assert len(notifier.sent) == 1


def test_daily_macro_retries_only_failed_outlet_after_news_window_advances(session):
    collect(session)
    ok, failed = Notifier("ok"), Notifier("failed", False)
    daily(session, [ok, failed], NOW + timedelta(hours=1))
    failed.ok = True
    daily(session, [ok, failed], NOW + timedelta(days=1))
    assert len(ok.sent) == 1 and len(failed.sent) == 2
    assert len(failed.sent[-1].items) == 2


def test_daily_does_not_resend_successful_legacy_standalone_notifications(session):
    notifier = Notifier()
    kwargs = {"now": NOW, "client": Client(), "dispatcher": DigestDispatcher([notifier])}
    run_data_digest(session, {"providers": ["bls"], "standalone_notifications": True}, **kwargs)
    run_calendar_digest(session, {"providers": ["bea"], "standalone_notifications": True}, **kwargs)
    assert len(notifier.sent) == 2
    result = daily(session, [notifier], NOW + timedelta(hours=1))
    assert result["macro_items"] == 0 and len(notifier.sent) == 2


def test_daily_picks_up_late_imports_and_ignores_overseas_delivery_state(session):
    collect(session)
    daily(session, [Notifier()], NOW + timedelta(minutes=30))
    batch = build_batch(session, secret="test", source_instance="oci-overseas", until=NOW + timedelta(hours=2))
    engine = create_engine("sqlite://")

    @sa_event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine) as target:
        notifier = Notifier()
        daily(target, [notifier], NOW + timedelta(hours=1))
        import_batch(target, batch, secret="test")
        import_batch(target, batch, secret="test")
        result = daily(target, [notifier], NOW + timedelta(hours=2))
        assert result["macro_items"] == 2 and len(notifier.sent) == 1
        daily(target, [notifier], NOW + timedelta(days=1))
        assert len(notifier.sent) == 1
    engine.dispose()


def test_daily_macro_respects_filters_and_exclusive_end(session):
    collect(session)
    notifier = Notifier()
    assert daily(session, [notifier], NOW)["items"] == 0
    assert daily(session, [notifier], NOW + timedelta(hours=1), selection={"allowed_topics": ["politics"]})["items"] == 0
    assert daily(session, [notifier], NOW + timedelta(hours=2), selection={"excluded_keywords": ["CPI", "GDP"]})["items"] == 0
    assert notifier.sent == []
    assert daily(session, [notifier], NOW + timedelta(hours=3))["macro_items"] == 2
