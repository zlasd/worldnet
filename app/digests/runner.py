from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db_session
from app.digests.config import DigestTaskConfig, parse_digest_task_config
from app.digests.dispatcher import DigestDispatcher, build_digest_dispatcher
from app.digests.llm import DigestLlmClient, select_digest_items
from app.digests.types import DigestCandidate, DigestDispatchPayload, DigestSelectionResult
from app.models.digest import DigestLog
from app.models.normalized_event import NormalizedEvent
from app.models.watchlist import WatchlistItem
from app.rules.priority_rules import determine_notification_priority


def _scheduler_timezone() -> ZoneInfo:
    return ZoneInfo(settings.scheduler_timezone)


def _to_utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def determine_digest_window(
    session: Session,
    digest_type: str,
    now: datetime,
    config: DigestTaskConfig,
) -> tuple[datetime, datetime]:
    if config.window.mode != "since_last_run":
        raise ValueError(f"Unsupported digest window mode: {config.window.mode}")

    window_end = _to_utc_naive(now)
    last_window_end = (
        session.query(func.max(DigestLog.window_end))
        .filter(DigestLog.digest_type == digest_type)
        .scalar()
    )
    if last_window_end is not None:
        return last_window_end, window_end

    timezone_ = _scheduler_timezone()
    local_now = now.astimezone(timezone_) if now.tzinfo else now.replace(tzinfo=timezone_)
    local_today_start = datetime.combine(
        local_now.date(),
        time.min,
        tzinfo=timezone_,
    )
    first_run_start = local_today_start - timedelta(days=1)
    return _to_utc_naive(first_run_start), window_end


def _watchlist_ids(session: Session) -> set[str]:
    return {item.instrument_id for item in session.query(WatchlistItem).all()}


def collect_digest_candidates(
    session: Session,
    *,
    window_start: datetime,
    window_end: datetime,
    config: DigestTaskConfig,
) -> list[DigestCandidate]:
    watchlist_ids = _watchlist_ids(session)
    events = (
        session.query(NormalizedEvent)
        .filter(NormalizedEvent.is_duplicate.is_(False))
        .filter(NormalizedEvent.detected_at >= window_start)
        .filter(NormalizedEvent.detected_at < window_end)
        .order_by(NormalizedEvent.detected_at.desc())
        .all()
    )

    candidates: list[DigestCandidate] = []
    allowed_priorities = set(config.selection.priorities)
    for event in events:
        if config.selection.include_watchlist_only and event.primary_instrument_id not in watchlist_ids:
            continue
        priority = determine_notification_priority(event, watchlist_ids)
        priority_value = getattr(priority, "value", priority)
        if priority_value not in allowed_priorities:
            continue
        candidates.append(
            DigestCandidate(
                event_id=event.event_id,
                title=event.title,
                summary=event.summary,
                priority=priority_value,
                event_type=event.event_type,
                severity=event.severity,
                actionability=event.actionability,
                source_tier=event.source_tier,
                detected_at=event.detected_at,
                event_time=event.event_time,
                instrument_id=event.primary_instrument_id,
            )
        )
        if len(candidates) >= config.selection.max_candidates:
            break
    return candidates


def render_digest_body(result: DigestSelectionResult, window_start: datetime, window_end: datetime) -> str:
    lines = [
        f"Window: {window_start.isoformat()} - {window_end.isoformat()} UTC",
        "",
        result.summary,
        "",
    ]
    if result.error:
        lines.extend([f"LLM note: {result.error}", ""])
    if not result.items:
        lines.append("No important events found.")
        return "\n".join(lines)

    for item in result.items:
        lines.extend(
            [
                f"{item.rank}. [{item.priority.upper()}] {item.title}",
                f"   Why it matters: {item.why_it_matters}",
                f"   Suggested action: {item.suggested_action}",
                f"   Event ID: {item.event_id}",
                "",
            ]
        )
    return "\n".join(lines).strip()


def run_important_daily_digest(
    session: Session,
    task_config: dict[str, Any] | None = None,
    *,
    now: datetime | None = None,
    dispatcher: DigestDispatcher | None = None,
    llm_client: DigestLlmClient | None = None,
) -> dict[str, Any]:
    config = parse_digest_task_config(task_config)
    now = now or datetime.now(_scheduler_timezone())
    dispatcher = dispatcher or build_digest_dispatcher()

    window_start, window_end = determine_digest_window(session, "important_daily", now, config)
    if window_start >= window_end:
        return {
            "digest_type": "important_daily",
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
            "candidates": 0,
            "items": 0,
            "digests": 0,
            "used_llm": False,
            "error": "empty_digest_window",
        }
    candidates = collect_digest_candidates(
        session,
        window_start=window_start,
        window_end=window_end,
        config=config,
    )
    selection = select_digest_items(candidates, config, client=llm_client)
    body = render_digest_body(selection, window_start, window_end)
    payload = DigestDispatchPayload(
        digest_type="important_daily",
        window_start=window_start,
        window_end=window_end,
        title=config.rendering.title,
        body=body,
        items=selection.items,
        last_error=selection.error,
    )
    should_send = bool(selection.items or config.rendering.include_empty_digest)
    digests = dispatcher.dispatch(
        session,
        payload,
        send=should_send,
        skip_reason=None if should_send else "no_digest_items",
    )
    session.flush()
    return {
        "digest_type": "important_daily",
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "candidates": len(candidates),
        "items": len(selection.items),
        "digests": len(digests),
        "used_llm": selection.used_llm,
        "error": selection.error,
    }


def run_digest(
    digest_type: str,
    task_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if digest_type != "important_daily":
        raise ValueError(f"Unsupported digest_type: {digest_type}")
    with get_db_session() as session:
        return run_important_daily_digest(session, task_config)
