import json
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine
from sqlalchemy import event as sa_event
from sqlalchemy.orm import Session

from app.db.base import Base
from app.digests.config import parse_digest_task_config
from app.digests.dispatcher import DigestDispatcher
from app.digests.runner import collect_digest_candidates
from app.macro_calendar.service import (
    active_notices,
    prepare_reminders,
    refresh_calendar,
    run_calendar_digest,
)
from app.macro_calendar.sources import (
    OfficialCalendarClient,
    parse_bea,
    parse_bls,
    parse_fed,
    parse_nbs,
)
from app.macro_calendar.types import CalendarConfig, CalendarRelease
from app.models.digest import DigestItem, DigestLog
from app.models.macro_calendar import MacroCalendarEntry
from app.models.normalized_event import NormalizedEvent
from app.models.source_document import SourceDocument
from app.notifications.base import NotificationResult
from app.sync.transfer import build_batch, import_batch
from app.tasks.task_config import load_task_definitions

NOW = datetime(2026, 11, 18, 7, tzinfo=ZoneInfo("Asia/Shanghai"))


def release(**updates):
    return CalendarRelease.model_validate({
        "provider": "bea", "key": "PCE:2026-10", "title": "Personal Income and Outlays, October 2026",
        "country": "US", "release_date": "2026-11-25", "release_time": "08:30",
        "timezone": "America/New_York", "source_url": "https://www.bea.gov/news/schedule",
        **updates,
    })


class Client:
    def __init__(self, releases=None, fails=False):
        self.releases = releases if releases is not None else [release()]
        self.fails = fails

    def fetch(self, provider, now):
        if self.fails:
            raise OSError("network unavailable")
        return self.releases


class Notifier:
    channel = "webhook"

    def __init__(self, outlet_id="test", ok=True):
        self.outlet_id, self.ok, self.sent = outlet_id, ok, []

    def send(self, payload):
        self.sent.append(payload)
        return NotificationResult(ok=self.ok, error=None if self.ok else "temporary failure")


def run(session, now=NOW, client=None, outlets=None, config=None):
    return run_calendar_digest(
        session, {"providers": ["bea"], **(config or {})}, now=now,
        client=client or Client(), dispatcher=DigestDispatcher(outlets or []),
    )


def test_seven_day_boundary_restart_and_provenance(session):
    notifier = Notifier()
    assert run(session, NOW - timedelta(days=1), outlets=[notifier])["items"] == 0
    assert run(session, outlets=[notifier])["reminders_created"] == 1
    session.commit()
    assert run(session, NOW + timedelta(hours=6), outlets=[notifier])["items"] == 0
    assert len(notifier.sent) == 1
    body = notifier.sent[0].message_body
    assert "提前 7 天" in body and "2026-11-25 21:30" in body
    assert session.query(SourceDocument).one().published_at is None
    assert session.query(NormalizedEvent).one().event_time is None
    assert session.query(DigestItem).count() == 1


def test_late_discovery_does_not_claim_seven_days_and_expires(session):
    notifier = Notifier()
    run(session, NOW + timedelta(days=2), outlets=[notifier])
    assert "临近发布补充提醒" in notifier.sent[0].message_body
    assert "提前 7 天" not in notifier.sent[0].message_body
    assert active_notices(session, NOW + timedelta(days=9)) == []


def test_no_outlet_keeps_digest_dependencies_then_new_outlet_can_send(session):
    run(session)
    assert session.query(DigestLog).one().status == "skipped"
    assert session.query(DigestItem).count() == 1
    notifier = Notifier()
    run(session, NOW + timedelta(hours=1), outlets=[notifier])
    assert len(notifier.sent) == 1


def test_partial_failure_retries_only_failed_outlet(session):
    success, failure = Notifier("success"), Notifier("failure", ok=False)
    run(session, outlets=[success, failure])
    failure.ok = True
    run(session, NOW + timedelta(hours=6), outlets=[success, failure])
    assert len(success.sent) == 1
    assert len(failure.sent) == 2
    run(session, NOW + timedelta(hours=12), outlets=[success, failure])
    assert len(failure.sent) == 2


def test_reschedule_corrects_then_reminds_on_new_seven_day_date(session):
    notifier = Notifier()
    run(session, outlets=[notifier])
    changed = Client([release(release_date="2026-12-10")])
    run(session, NOW + timedelta(days=1), client=changed, outlets=[notifier])
    assert len(notifier.sent) == 2
    assert "日程更正" in notifier.sent[-1].message_body
    assert "原定" in notifier.sent[-1].message_body
    run(session, NOW + timedelta(days=2), client=changed, outlets=[notifier])
    assert len(notifier.sent) == 2
    run(session, datetime(2026, 12, 3, 7, tzinfo=NOW.tzinfo), client=changed, outlets=[notifier])
    assert len(notifier.sent) == 3
    assert "提前 7 天" in notifier.sent[-1].message_body


@pytest.mark.parametrize("status", ["cancelled", "postponed"])
def test_cancelled_or_undated_release_replaces_old_notice(session, status):
    run(session)
    run(session, NOW + timedelta(hours=1), client=Client([
        release(status=status, release_date=None, release_time=None)
    ]))
    notices = active_notices(session, NOW + timedelta(hours=2))
    assert len(notices) == 1 and "日程更正" in notices[0][0].title
    candidates = collect_digest_candidates(
        session, window_start=(NOW - timedelta(hours=1)).astimezone(timezone.utc).replace(tzinfo=None),
        window_end=(NOW + timedelta(hours=2)).astimezone(timezone.utc).replace(tzinfo=None),
        config=parse_digest_task_config({"llm": {"enabled": False}}),
    )
    assert len(candidates) == 1 and candidates[0].priority == "p1"
    assert "日程更正" in candidates[0].title


def test_failed_refresh_does_not_delete_schedule_or_emit_stale_notice(session):
    run(session, NOW - timedelta(days=3))
    outcome = run(session, client=Client(fails=True))
    assert outcome["warnings"] and outcome["reminders_created"] == 0
    assert session.query(MacroCalendarEntry).count() == 1
    assert session.query(NormalizedEvent).count() == 0


def test_recent_cache_keeps_true_verification_time_on_fetch_failure(session):
    run(session, NOW - timedelta(days=1))
    notifier = Notifier()
    run(session, client=Client(fails=True), outlets=[notifier])
    assert len(notifier.sent) == 1
    assert "核验时间：2026-11-17 07:00" in notifier.sent[0].message_body
    metadata = json.loads(session.query(SourceDocument).one().metadata_)
    assert datetime.fromisoformat(metadata["calendar_checked_at"]) == NOW - timedelta(days=1)


def test_date_only_reminder_labels_source_timezone(session):
    notifier = Notifier()
    run(session, client=Client([release(release_time=None)]), outlets=[notifier])
    assert "America/New_York 当地日期，具体时间待公布" in notifier.sent[0].message_body


def test_naive_now_and_undated_scheduled_release_are_rejected(session):
    with pytest.raises(ValueError, match="aware"):
        run(session, datetime(2026, 11, 18))
    with pytest.raises(ValueError, match="official date"):
        release(release_date=None)


def test_preparation_rolls_back_calendar_and_notice_together(session):
    config = CalendarConfig(providers=["bea"])
    refresh_calendar(session, config, NOW, Client())
    assert prepare_reminders(session, config, NOW) == 1
    session.rollback()
    assert session.query(MacroCalendarEntry).count() == 0
    assert session.query(NormalizedEvent).count() == 0
    assert session.query(SourceDocument).count() == 0


def test_date_only_and_dst_do_not_invent_time():
    summer = release(release_date="2026-07-30")
    winter = release()
    assert summer.instant().astimezone(NOW.tzinfo).hour == 20
    assert winter.instant().astimezone(NOW.tzinfo).hour == 21
    date_only = release(release_time=None)
    assert date_only.instant() is None
    # A UTC offset transition does not shift the reminder off its local calendar day.
    assert release(release_date="2026-11-01").display_date("Asia/Shanghai") == date(2026, 11, 1)


def test_nbs_rowspans_blank_month_and_multiple_releases():
    months = "".join(f"<th>{i}月</th>" for i in range(1, 13))
    days = ["31/六", "……", "4/三注5 31/二"] + ["30/四"] * 9
    html = f'<table><tr><th>序号</th><th>内容</th>{months}</tr><tr><td rowspan="2">1</td><td rowspan="2">采购经理指数月度报告</td>'
    html += "".join(f"<td>{d}</td>" for d in days) + "</tr><tr>"
    html += "".join("<td>9:30</td>" for _ in range(12)) + "</tr></table>"
    releases = parse_nbs(html, 2026, "https://www.stats.gov.cn/calendar")
    assert len(releases) == 12
    assert releases[0].release_time == time(9, 30)
    assert not any(r.release_date.month == 2 for r in releases)
    assert [r.release_date.day for r in releases if r.release_date.month == 3] == [4, 31]
    assert len({r.key for r in releases}) == 12


def test_bls_explicit_dates_and_reference_period_identity():
    html = '<table><tr><td>Friday, November 6, 2026</td><td>08:30 AM</td><td>Employment Situation for October 2026</td></tr><tr><td>November 11, 2026</td><td></td><td>Holiday</td></tr></table>'
    parsed = parse_bls(html, "https://www.bls.gov/schedule/2026/home.htm")
    assert len(parsed) == 1
    assert parsed[0].release_date == date(2026, 11, 6)
    assert parsed[0].key == "Employment Situation for October 2026"
    assert parse_bls(html.replace("November 6", "November 9"), parsed[0].source_url)[0].key == parsed[0].key


def test_bea_filters_non_macro_and_preserves_date():
    html = '<table id="release-schedule-table"><thead><tr><th>Year 2026</th></tr></thead><tbody><tr><td class="scheduled-date"><div class="release-date">November 25</div><small>8:30 AM</small></td><td class="release-title">Personal Income and Outlays, October 2026</td></tr></tbody></table>'
    parsed = parse_bea(html)
    assert parsed[0].release_date == date(2026, 11, 25)
    assert parsed[0].release_time == time(8, 30)


def test_fed_uses_meeting_end_date_and_only_explicit_minutes_dates():
    html = '<div class="panel"><h4>2027 FOMC Meetings</h4><div class="fomc-meeting"><div class="fomc-meeting__month">Jan/Feb</div><div class="fomc-meeting__date">31-1*</div></div></div>'
    parsed = parse_fed(html)
    assert len(parsed) == 1
    assert parsed[0].release_date == date(2027, 2, 1)
    assert parsed[0].release_time is None
    assert "SEP" in parsed[0].title


def test_unrecognized_source_fails_closed():
    class Response:
        text = "<html>temporarily unavailable</html>"

        def raise_for_status(self):
            pass
    with pytest.raises(ValueError, match="No recognized"):
        OfficialCalendarClient(get=lambda *a, **kw: Response()).fetch("bea", NOW)


def test_overseas_notice_sync_replay_and_mainland_dispatch(session, tmp_path):
    run(session)
    until = datetime.now(timezone.utc) + timedelta(days=1)
    batch = build_batch(session, secret="test", source_instance="oci-overseas", until=until)
    engine = create_engine(f"sqlite:///{tmp_path / 'target.db'}")

    @sa_event.listens_for(engine, "connect")
    def foreign_keys(dbapi_connection, _):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    notifier = Notifier()
    with Session(engine) as target:
        import_batch(target, batch, secret="test")
        import_batch(target, batch, secret="test")
        assert target.query(MacroCalendarEntry).count() == 0
        assert target.query(DigestItem).count() == 1
        run(target, NOW + timedelta(hours=1), config={"providers": []}, outlets=[notifier])
        run(target, NOW + timedelta(hours=2), config={"providers": []}, outlets=[notifier])
        assert len(notifier.sent) == 1
        assert "2026-11-25 21:30" in notifier.sent[0].message_body
    engine.dispose()


def test_profiles_route_calendars_to_their_collectors():
    local = load_task_definitions(custom_dir="/nonexistent")
    overseas = load_task_definitions(custom_dir="config/tasks/overseas")
    for tasks, providers in [(local, ["nbs"]), (overseas, ["bls", "bea", "fed"])]:
        task = next(t for t in tasks if t.task_id == "macro-calendar-reminders")
        assert task.kind == "digest" and task.digest_type == "macro_calendar"
        assert task.source_config["providers"] == providers
        assert task.cron == ("0 7,13,19 * * *" if providers == ["nbs"] else "40 6,12,18 * * *")
