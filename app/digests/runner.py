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
from app.digests.types import (
    DigestCandidate,
    DigestDispatchPayload,
    DigestSelectionResult,
    _format_iso_minute,
)
from app.index_futures.commentary import get_or_create_market_commentary
from app.index_futures.metrics import build_market_metrics
from app.index_futures.official import OfficialMarketDataClient
from app.index_futures.paper import process_paper_strategy
from app.index_futures.report import IndexFuturesDigestSection, render_market_plain
from app.index_futures.service import update_basis_snapshots
from app.models.digest import DigestLog
from app.models.normalized_event import NormalizedEvent
from app.models.source_document import SourceDocument
from app.models.watchlist import WatchlistItem
from app.rules.priority_rules import determine_notification_priority
from app.utils.text import summarize_text


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
        source_document = session.get(SourceDocument, event.document_id)
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
                summary=event.summary or summarize_text(source_document.raw_text if source_document else None),
                priority=priority_value,
                event_type=event.event_type,
                severity=event.severity,
                actionability=event.actionability,
                source_name=source_document.source_name if source_document else None,
                source_tier=event.source_tier,
                detected_at=event.detected_at,
                event_time=event.event_time,
                instrument_id=event.primary_instrument_id,
            )
        )
        if len(candidates) >= config.selection.max_candidates:
            break
    return candidates


def render_digest_body(
    result: DigestSelectionResult,
    window_start: datetime,
    window_end: datetime,
    market_section: IndexFuturesDigestSection | None = None,
) -> str:
    lines = [
        f"时间窗口：{_format_iso_minute(window_start)} - {_format_iso_minute(window_end)}",
        "",
    ]
    if market_section is not None:
        lines.extend(["一、重要新闻", result.summary, ""])
    else:
        lines.extend([result.summary, ""])
    if result.error:
        lines.extend([f"LLM 备注：{result.error}", ""])
    if not result.items:
        lines.append("未发现重要事项。")
        if market_section is not None:
            lines.extend(["", render_market_plain(market_section)])
        return "\n".join(lines)

    for item in result.items:
        lines.extend(
            [
                f"{item.rank}. [{item.priority.upper()}] {item.title}",
                f"   摘要：{item.summary}",
                "",
            ]
        )
    if market_section is not None:
        lines.extend([render_market_plain(market_section)])
    return "\n".join(lines).strip()


def run_important_daily_digest(
    session: Session,
    task_config: dict[str, Any] | None = None,
    *,
    now: datetime | None = None,
    dispatcher: DigestDispatcher | None = None,
    llm_client: DigestLlmClient | None = None,
    market_llm_client: DigestLlmClient | None = None,
    market_data_client: OfficialMarketDataClient | None = None,
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
    market_section: IndexFuturesDigestSection | None = None
    market_trade_date = None
    market_warnings: list[str] = []
    paper_trades = 0
    market_used_llm = False
    basis_config = config.market_sections.index_futures_basis
    if basis_config.enabled:
        try:
            basis = update_basis_snapshots(
                session,
                as_of=now.astimezone(_scheduler_timezone()).date() if now.tzinfo else now.date(),
                history_days=basis_config.history_days,
                products=basis_config.products,
                client=market_data_client,
            )
            market_trade_date = basis.trade_date
            market_warnings.extend(basis.warnings)
            if basis.trade_date is not None:
                strategy = process_paper_strategy(
                    session,
                    config=config.paper_strategy,
                    products=basis_config.products,
                    up_to=basis.trade_date,
                )
                paper_trades = strategy.trades
                market_warnings.extend(strategy.warnings)
                metrics = build_market_metrics(
                    session,
                    trade_date=basis.trade_date,
                    config=config.paper_strategy,
                    products=basis_config.products,
                    warnings=market_warnings,
                )
                commentary = get_or_create_market_commentary(
                    session,
                    metrics=metrics,
                    config=config.market_commentary,
                    client=market_llm_client,
                )
                market_used_llm = commentary.used_llm
                market_section = IndexFuturesDigestSection(
                    metrics=metrics,
                    commentary=commentary,
                    warnings=tuple(market_warnings),
                )
            else:
                market_section = IndexFuturesDigestSection(
                    metrics=None,
                    commentary=None,
                    warnings=tuple(market_warnings),
                )
        except Exception as exc:
            market_warnings.append(f"股指期货日报模块异常：{str(exc) or exc.__class__.__name__}")
            market_section = IndexFuturesDigestSection(
                metrics=None,
                commentary=None,
                warnings=tuple(market_warnings),
            )
    body = render_digest_body(selection, window_start, window_end, market_section)
    payload = DigestDispatchPayload(
        digest_type="important_daily",
        window_start=window_start,
        window_end=window_end,
        title=config.rendering.title,
        summary=selection.summary,
        body=body,
        items=selection.items,
        last_error=selection.error,
        market_section=market_section,
    )
    should_send = bool(
        selection.items or config.rendering.include_empty_digest or market_section is not None
    )
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
        "market_trade_date": market_trade_date.isoformat() if market_trade_date else None,
        "market_warnings": list(dict.fromkeys(market_warnings)),
        "market_used_llm": market_used_llm,
        "paper_trades": paper_trades,
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
