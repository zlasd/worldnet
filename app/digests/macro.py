"""Append official macro records to the daily digest without LLM rewriting."""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.digests.config import DigestTaskConfig
from app.digests.selection import contains_keyword, matching_topics
from app.digests.types import DigestSelectedItem
from app.models.digest import DigestItem, DigestLog

MACRO_EVENT_TYPES = {"macro_release_reminder", "macro_data_release", "central_bank_decision"}


def collect_macro_items(session: Session, window_end: datetime, config: DigestTaskConfig) -> list[DigestSelectedItem]:
    from app.macro_calendar.service import active_notices
    from app.macro_data.service import active_data_events

    # Do not use the news window's lower bound: overseas events may arrive after
    # that window closed, and an outlet may have failed on the previous day.
    now = window_end.replace(tzinfo=timezone.utc)
    selection = config.selection
    if "p1" not in selection.priorities or selection.include_watchlist_only:
        return []
    candidates = active_data_events(session, now) + active_notices(session, now)
    items = []
    for event, doc in sorted(candidates, key=lambda pair: (pair[0].detected_at, pair[0].event_id)):
        if event.detected_at >= window_end:
            continue  # Keep the upper bound exclusive, including at midnight.
        text = f"{event.title} {doc.raw_text or event.summary or ''}"
        if any(contains_keyword(text, word) for word in selection.excluded_keywords):
            continue
        if selection.allowed_topics and not matching_topics(event.title, text, "economy").intersection(selection.allowed_topics):
            continue
        items.append(DigestSelectedItem(
            event_id=event.event_id, rank=len(items) + 1, priority="p1",
            title=event.title, summary=event.summary or doc.raw_text or "",
            source_name=doc.source_name, source_url=doc.url, published_at=doc.published_at,
            selection_reason="官方宏观公布值、央行政策或发布预告；随日报发送",
        ))
    return items


def pending_macro_items(session: Session, items: list[DigestSelectedItem], outlet_id: str) -> list[DigestSelectedItem]:
    if not items:
        return []
    completed = session.query(DigestItem.event_id).join(DigestLog).filter(
        DigestLog.source_instance.is_(None), DigestLog.outlet_id == outlet_id,
        DigestItem.event_id.in_([item.event_id for item in items]),
    )
    if outlet_id == "none":
        # Collection-only logs are dependencies for sync, not daily delivery.
        completed = completed.filter(DigestLog.digest_type == "important_daily", DigestLog.status == "skipped")
    else:
        # Also recognize successful legacy standalone deliveries during rollout.
        completed = completed.filter(
            DigestLog.digest_type.in_(["important_daily", "macro_data", "macro_calendar"]),
            DigestLog.status == "sent",
        )
    delivered = {event_id for (event_id,) in completed.all()}
    return [item for item in items if item.event_id not in delivered]
