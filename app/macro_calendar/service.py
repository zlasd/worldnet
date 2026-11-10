from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.digests.dispatcher import DigestDispatcher, build_digest_dispatcher
from app.digests.types import DigestDispatchPayload, DigestSelectedItem
from app.macro_calendar.sources import OfficialCalendarClient
from app.macro_calendar.types import CalendarConfig, CalendarRelease
from app.models.digest import DigestItem, DigestLog
from app.models.macro_calendar import MacroCalendarEntry
from app.models.normalized_event import NormalizedEvent
from app.models.source_document import SourceDocument
from app.utils.logging import get_logger

EVENT_TYPE = "macro_release_reminder"
DIGEST_TYPE = "macro_calendar"
logger = get_logger(__name__)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _schedule_hash(release: CalendarRelease) -> str:
    return _hash(release.model_dump_json(include={
        "release_date", "release_time", "timezone", "status",
    }))


def _schedule_text(release: CalendarRelease, display_timezone: str) -> str:
    if release.status != "scheduled":
        return "已取消" if release.status == "cancelled" else "已延期，日期待公布"
    instant = release.instant()
    if instant:
        local = instant.astimezone(ZoneInfo(display_timezone))
        return f"{local:%Y-%m-%d %H:%M}（{display_timezone}）"
    return f"{release.release_date}（{release.timezone} 当地日期，具体时间待公布）"


def _emit(
    session: Session, entry: MacroCalendarEntry, release: CalendarRelease,
    now: datetime, config: CalendarConfig, *, old: CalendarRelease | None = None,
) -> None:
    display_date = release.display_date(config.display_timezone)
    remaining = (display_date - now.astimezone(ZoneInfo(config.display_timezone)).date()).days if display_date else None
    if old:
        prefix = "日程更正"
        summary = f"原定：{_schedule_text(old, config.display_timezone)}；最新：{_schedule_text(release, config.display_timezone)}。"
    else:
        prefix = f"提前 {config.lead_days} 天预告" if remaining == config.lead_days else "临近发布补充提醒"
        summary = f"计划发布：{_schedule_text(release, config.display_timezone)}。"
        if remaining != config.lead_days:
            summary += "首次确认或恢复运行时已进入提前提醒窗口。"
    checked_at = entry.last_checked_at.replace(tzinfo=timezone.utc).astimezone(
        ZoneInfo(config.display_timezone)
    )
    summary += f"日程核验时间：{checked_at:%Y-%m-%d %H:%M}。以官方后续调整为准。"
    title = f"【{prefix}】{release.title}"
    metadata = {
        "topic": "economy", "calendar_entry_id": entry.entry_id,
        "calendar_release": release.model_dump(mode="json"),
        "calendar_notice": "change" if old else "advance",
        "calendar_checked_at": entry.last_checked_at.replace(tzinfo=timezone.utc).isoformat(),
    }
    doc = SourceDocument(
        source_name=f"{release.provider}_official_calendar", source_type="macro_calendar",
        source_tier="official", title=title, url=release.source_url,
        # A calendar reminder is not an already-published statistical release.
        published_at=None, observed_at=_utc(now), created_at=_utc(now), language="zh",
        raw_text=summary, metadata_=json.dumps(metadata, ensure_ascii=False),
        content_hash=_hash(title + summary), ingestion_status="processed",
    )
    session.add(doc)
    session.flush()
    session.add(NormalizedEvent(
        document_id=doc.document_id, event_type=EVENT_TYPE,
        event_subtype="schedule_change" if old else "advance_notice",
        market=release.country, title=title, summary=summary,
        event_time=None, detected_at=_utc(now), created_at=_utc(now),
        severity="high", sentiment="neutral", actionability="monitor",
        source_tier="official", confidence_score=1.0,
    ))
    session.flush()


def refresh_calendar(
    session: Session, config: CalendarConfig, now: datetime, client: OfficialCalendarClient,
) -> tuple[int, list[str]]:
    warnings = []
    refreshed = 0
    for provider in dict.fromkeys(config.providers):
        try:
            releases = client.fetch(provider, now)
            if not releases or any(r.provider != provider for r in releases):
                raise ValueError("Invalid calendar response")
        except Exception as exc:
            warning = f"{provider} 日历更新失败（{type(exc).__name__}）；保留上次确认日程"
            warnings.append(warning)
            logger.warning(warning)
            continue
        for release in releases:
            entry_id = _hash(f"{release.provider}:{release.key}")
            version = _schedule_hash(release)
            entry = session.get(MacroCalendarEntry, entry_id)
            if entry is None:
                entry = MacroCalendarEntry(
                    entry_id=entry_id, provider=provider, payload=release.model_dump_json(),
                    schedule_hash=version, last_checked_at=_utc(now),
                )
                session.add(entry)
            else:
                old = CalendarRelease.model_validate_json(entry.payload)
                entry.last_checked_at = _utc(now)
                if entry.schedule_hash != version and entry.reminded_hash is not None:
                    if not (old.is_past(now) and release.is_past(now)):
                        _emit(session, entry, release, now, config, old=old)
                entry.payload = release.model_dump_json()
                entry.schedule_hash = version
            refreshed += 1
        session.flush()
    return refreshed, warnings


def prepare_reminders(session: Session, config: CalendarConfig, now: datetime) -> int:
    today = now.astimezone(ZoneInfo(config.display_timezone)).date()
    count = 0
    notices = _latest_notices(session)
    for entry in session.query(MacroCalendarEntry).filter(
        MacroCalendarEntry.provider.in_(config.providers)
    ).all():
        # Do not silently announce a schedule that has not been confirmed recently.
        if entry.last_checked_at < _utc(now) - timedelta(hours=config.max_stale_hours):
            logger.warning("Skipping stale macro calendar entry=%s provider=%s", entry.entry_id, entry.provider)
            continue
        release = CalendarRelease.model_validate_json(entry.payload)
        if release.status != "scheduled" or release.is_past(now):
            continue
        release_date = release.display_date(config.display_timezone)
        if release_date is None or not 0 <= (release_date - today).days <= config.lead_days:
            continue
        if entry.reminded_hash == entry.schedule_hash:
            continue
        # A correction generated in this run is already a reminder of the new date.
        latest = notices.get(entry.entry_id)
        if not (latest and latest[0].detected_at == _utc(now) and latest[2]["calendar_notice"] == "change"):
            _emit(session, entry, release, now, config)
        entry.reminded_hash = entry.schedule_hash
        count += 1
    session.flush()
    return count


def _latest_notices(session: Session, now: datetime | None = None) -> dict:
    latest = {}
    rows = session.query(NormalizedEvent, SourceDocument).join(
        SourceDocument, SourceDocument.document_id == NormalizedEvent.document_id
    ).filter(
        NormalizedEvent.event_type == EVENT_TYPE,
        NormalizedEvent.is_duplicate.is_(False),
    ).order_by(NormalizedEvent.detected_at.desc(), NormalizedEvent.created_at.desc()).all()
    for event, doc in rows:
        if now is not None and event.detected_at > _utc(now):
            continue
        metadata = json.loads(doc.metadata_ or "{}")
        if entry_id := metadata.get("calendar_entry_id"):
            latest.setdefault(entry_id, (event, doc, metadata))
    return latest


def active_notices(session: Session, now: datetime, max_age_days: int = 7) -> list:
    notices = []
    for event, doc, metadata in _latest_notices(session, now).values():
        release = CalendarRelease.model_validate(metadata["calendar_release"])
        if release.is_past(now) or event.detected_at < _utc(now) - timedelta(days=max_age_days):
            continue
        notices.append((event, doc))
    return sorted(notices, key=lambda item: (item[0].detected_at, item[0].event_id))


def run_calendar_digest(
    session: Session, task_config: dict | None = None, *, now: datetime | None = None,
    client: OfficialCalendarClient | None = None, dispatcher: DigestDispatcher | None = None,
) -> dict:
    config = CalendarConfig.model_validate(task_config or {})
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Calendar reminders require an aware current time")
    dispatcher = (dispatcher or build_digest_dispatcher()) if config.standalone_notifications else DigestDispatcher([])
    refreshed, warnings = refresh_calendar(session, config, now, client or OfficialCalendarClient())
    created = prepare_reminders(session, config, now)
    # Includes imported notices: calendar state stays on its collector, while ordinary
    # source documents/events and digest items use the existing one-way sync protocol.
    candidates = active_notices(session, now, config.lead_days)
    log_count = 0
    item_count = 0
    outlets = dispatcher.notifiers or [None]
    for notifier in outlets:
        outlet_id = notifier.outlet_id if notifier else "none"
        completed = {
            event_id for (event_id,) in session.query(DigestItem.event_id).join(
                DigestLog, DigestLog.digest_id == DigestItem.digest_id
            ).filter(
                DigestLog.digest_type == DIGEST_TYPE,
                DigestLog.source_instance.is_(None),
                DigestLog.outlet_id == outlet_id,
                DigestLog.status == ("sent" if notifier else "skipped"),
            ).all()
        }
        items = [DigestSelectedItem(
            event_id=event.event_id, rank=i + 1, priority="p1", title=event.title,
            summary=event.summary or "", source_name=doc.source_name, source_url=doc.url,
            selection_reason="官方日程提前提醒／日程更正",
        ) for i, (event, doc) in enumerate(
            (pair for pair in candidates if pair[0].event_id not in completed)
        )]
        if not items:
            continue
        summary = f"共 {len(items)} 项宏观数据或央行日程预告。"
        body = summary + "\n\n" + "\n\n".join(
            f"{item.rank}. {item.title}\n{item.summary}\n官方日程：{item.source_url}" for item in items
        )
        if warnings:
            body += "\n\n" + "\n".join(warnings)
        payload = DigestDispatchPayload(
            digest_type=DIGEST_TYPE, window_start=min(e.detected_at for e, _ in candidates),
            window_end=_utc(now), title=config.title, summary=summary, body=body,
            items=items, last_error="；".join(warnings) or None,
        )
        logs = DigestDispatcher([notifier] if notifier else []).dispatch(session, payload)
        log_count += len(logs)
        item_count += len(items)
    return {
        "digest_type": DIGEST_TYPE, "refreshed": refreshed, "reminders_created": created,
        "items": item_count, "digests": log_count, "warnings": warnings,
    }
