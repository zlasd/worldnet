"""Immutable observation snapshots use WorldNet's existing document/event sync."""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy.orm import Session

from app.digests.dispatcher import DigestDispatcher, build_digest_dispatcher
from app.digests.types import DigestDispatchPayload, DigestSelectedItem
from app.macro_data.sources import OfficialDataClient
from app.macro_data.types import DataConfig, Reading, Release
from app.models.digest import DigestItem, DigestLog
from app.models.normalized_event import NormalizedEvent
from app.models.source_document import SourceDocument
from app.utils.logging import get_logger

SOURCE_TYPE = "macro_data"
EVENT_TYPES = {"macro_data_release", "central_bank_decision"}
logger = get_logger(__name__)


def utc_naive(now: datetime) -> datetime:
    if now.tzinfo is None:
        raise ValueError("Macro data collection requires an aware timestamp")
    return now.astimezone(timezone.utc).replace(tzinfo=None)


def snapshots(session: Session, *, history: bool = False) -> list[tuple]:
    documents = session.query(SourceDocument).filter_by(source_type=SOURCE_TYPE).order_by(
        SourceDocument.observed_at.desc(), SourceDocument.created_at.desc(),
    ).all()
    result, seen = [], set()
    for doc in documents:
        metadata = json.loads(doc.metadata_)
        release = Release.model_validate(metadata["macro_release"])
        if history or release.key not in seen:
            result.append((doc, release, metadata))
        seen.add(release.key)
    return result


def semantic_hash(release: Release) -> str:
    # Capture numeric changes, missing-value flags, footnotes and official vintages.
    # Website navigation, fetch times and markup changes must not create revisions.
    values = []
    for item in sorted(release.readings, key=lambda r: (r.series_id, r.period)):
        value = item.model_dump(mode="json")
        if item.value is not None:
            value["value"] = format(item.value.normalize(), "f") if item.value else "0"
        values.append(value)
    facts = {
        "key": release.key, "vintage": release.vintage,
        "readings": values,
        "policy": release.text if release.kind == "policy" else None,
    }
    return hashlib.sha256(json.dumps(facts, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def display(reading: Reading) -> str:
    return "缺数" if reading.value is None else f"{reading.value} {reading.unit}"


def store_releases(session: Session, releases: list[Release], now: datetime) -> dict:
    timestamp = utc_naive(now)
    existing = {release.key: (doc, release, metadata) for doc, release, metadata in snapshots(session)}
    known_groups = {(r.provider, r.group) for _, r, _ in existing.values()}
    newest = {}
    for release in releases:
        group = release.provider, release.group
        newest[group] = max(newest.get(group, ""), release.period)
    saved = events = 0
    # Earlier periods are available when constructing the latest period's comparison.
    for release in sorted(releases, key=lambda r: (r.provider, r.group, r.period)):
        previous = existing.get(release.key)
        version = semantic_hash(release)
        if previous and previous[2]["value_hash"] == version:
            continue
        revision = previous is not None
        baseline = not revision and (release.provider, release.group) not in known_groups
        prefix = "数据修订" if revision else "首次采集快照" if baseline else "数据更新"
        title = f"【{prefix}】{release.title}"[:500]
        comparisons = {}
        for item in release.readings:
            earlier = [r for _, old, _ in existing.values() for r in old.readings
                       if r.series_id == item.series_id and r.period < item.period
                       and r.unit == item.unit and r.adjustment == item.adjustment]
            if earlier:
                comparisons[item.series_id] = max(earlier, key=lambda r: r.period).model_dump(mode="json")
        lines = [f"统计期／政策公告日：{release.period}。"]
        if baseline:
            lines.append("首次建立数据基线，可能包含此前发布的数据。")
        old_values = {r.series_id: r for r in previous[1].readings} if previous else {}
        for item in release.readings:
            line = f"{item.name}：{display(item)}"
            if item.adjustment != "unspecified":
                line += "（季调）" if item.adjustment == "SA" else "（未季调）"
            if item.basis != "官方公布值":
                line += "〔计算值〕"
            if item.notes:
                line += "〔官方备注：" + "；".join(item.notes) + "〕"
            if item.series_id in old_values and old_values[item.series_id] != item:
                line += f"；上次抓取值：{display(old_values[item.series_id])}"
            elif item.series_id in comparisons:
                prev = Reading.model_validate(comparisons[item.series_id])
                line += f"；前期记录 {prev.period}：{display(prev)}"
            lines.append(line + "。")
        if release.kind == "policy":
            lines.append("政策原文摘录：" + release.text[:1000])
        if release.published_at:
            lines.append(f"官方发布时间：{release.published_at.isoformat()}。")
        elif release.published_date:
            lines.append(f"官方发布日期：{release.published_date}；未提供具体时刻。")
        else:
            lines.append("来源未提供这批数值的原始发布时间；抓取时间不作为发布时间。")
        if release.publication_note:
            lines.append(release.publication_note + "。")
        prior_id = previous[0].document_id if previous else "initial"
        document_id = str(uuid5(NAMESPACE_URL, f"worldnet:macro:{release.key}:{version}:{prior_id}"))
        metadata = {
            "topic": "economy", "macro_release": release.model_dump(mode="json"),
            "value_hash": version, "notice_kind": "revision" if revision else "baseline" if baseline else "update",
            "previous_document_id": previous[0].document_id if previous else None,
            "previous_readings": [r.model_dump(mode="json") for r in previous[1].readings] if previous else [],
            "previous_periods": comparisons, "collected_at": now.isoformat(),
        }
        doc = SourceDocument(
            document_id=document_id, source_name=f"{release.provider}_official_data", source_type=SOURCE_TYPE,
            source_tier="official", title=title, url=release.source_url,
            published_at=utc_naive(release.published_at) if release.published_at else None,
            observed_at=timestamp, created_at=timestamp, language="zh",
            raw_text="\n".join(lines), metadata_=json.dumps(metadata, ensure_ascii=False),
            content_hash=hashlib.sha256(document_id.encode()).hexdigest(), ingestion_status="processed",
        )
        session.add(doc)
        session.flush()
        # Initial historical observations remain queryable without flooding the digest.
        if revision or not baseline or release.period == newest[release.provider, release.group]:
            session.add(NormalizedEvent(
                document_id=doc.document_id,
                event_type="central_bank_decision" if release.kind == "policy" else "macro_data_release",
                event_subtype=metadata["notice_kind"], market=release.country,
                title=title, summary=doc.raw_text, event_time=doc.published_at,
                detected_at=timestamp, created_at=timestamp, severity="high", sentiment="neutral",
                source_tier="official", confidence_score=1.0, actionability="monitor",
            ))
            events += 1
        existing[release.key] = doc, release, metadata
        saved += 1
    session.flush()
    return {"snapshots_created": saved, "events_created": events}


def active_data_events(session: Session, now: datetime, max_age_days: int = 3) -> list:
    latest_ids = {doc.document_id for doc, _, _ in snapshots(session)}
    return [(event, doc) for event, doc in session.query(NormalizedEvent, SourceDocument).join(
        SourceDocument, NormalizedEvent.document_id == SourceDocument.document_id
    ).filter(NormalizedEvent.event_type.in_(EVENT_TYPES), NormalizedEvent.is_duplicate.is_(False),
             NormalizedEvent.detected_at <= utc_naive(now),
             NormalizedEvent.detected_at >= utc_naive(now) - timedelta(days=max_age_days)
             ).order_by(NormalizedEvent.detected_at, NormalizedEvent.event_id).all()
            if doc.document_id in latest_ids]


def run_data_digest(session: Session, task_config: dict | None = None, *, now=None, client=None, dispatcher=None) -> dict:
    config = DataConfig.model_validate(task_config or {})
    now = now or datetime.now(timezone.utc)
    utc_naive(now)
    client = client or OfficialDataClient()
    dispatcher = dispatcher or build_digest_dispatcher()
    warnings, releases = [], []
    for provider in dict.fromkeys(config.providers):
        try:
            fetched = client.fetch(provider, now)
            if not fetched or any(r.provider != provider for r in fetched):
                raise ValueError("Invalid source response")
            releases.extend(fetched)
            warnings.extend(getattr(client, "warnings", []))
        except Exception as exc:
            warnings.append(f"{provider} 公布值获取失败（{type(exc).__name__}），未覆盖已有记录")
    warnings = list(dict.fromkeys(warnings))
    for warning in warnings:
        logger.warning(warning)
    result = store_releases(session, releases, now)
    candidates = active_data_events(session, now, config.notification_max_age_days)
    item_count = log_count = 0
    for notifier in dispatcher.notifiers or [None]:
        outlet = notifier.outlet_id if notifier else "none"
        completed = {eid for (eid,) in session.query(DigestItem.event_id).join(DigestLog).filter(
            DigestLog.digest_type == SOURCE_TYPE, DigestLog.source_instance.is_(None),
            DigestLog.outlet_id == outlet, DigestLog.status == ("sent" if notifier else "skipped"),
        ).all()}
        pending = [(e, d) for e, d in candidates if e.event_id not in completed]
        if not pending:
            continue
        items = [DigestSelectedItem(event_id=e.event_id, rank=i + 1, priority="p1", title=e.title,
                                    summary=e.summary or "", source_name=d.source_name, source_url=d.url,
                                    selection_reason="官方公布值／央行决定及修订") for i, (e, d) in enumerate(pending)]
        summary = f"共 {len(items)} 项数据公布值、政策决定或修订。"
        if warnings:
            # HTML mail and image notifications render summary/items, not body.
            summary += " 采集状态：" + "；".join(warnings)
        payload = DigestDispatchPayload(
            digest_type=SOURCE_TYPE, window_start=min(e.detected_at for e, _ in pending), window_end=utc_naive(now),
            title=config.title, summary=summary,
            body=summary + "\n\n" + "\n\n".join(f"{i.rank}. {i.title}\n{i.summary}\n原文：{i.source_url}" for i in items),
            items=items, last_error="；".join(warnings) or None,
        )
        log_count += len(DigestDispatcher([notifier] if notifier else []).dispatch(session, payload))
        item_count += len(items)
    return {**result, "releases_fetched": len(releases), "items": item_count, "digests": log_count, "warnings": warnings}


def observations(session: Session, *, series_id=None, country=None, period=None, history=False, limit=200) -> list[dict]:
    result = []
    for doc, release, metadata in snapshots(session, history=history):
        if country and release.country != country:
            continue
        for item in release.readings:
            if series_id and item.series_id != series_id or period and item.period != period:
                continue
            result.append({**item.model_dump(mode="json"), "country": release.country,
                           "provider": release.provider, "source_url": release.source_url,
                           "published_at": release.published_at.isoformat() if release.published_at else None,
                           "published_date": release.published_date.isoformat() if release.published_date else None,
                           "publication_note": release.publication_note,
                           "observed_at": doc.observed_at.replace(tzinfo=timezone.utc).isoformat(),
                           "document_id": doc.document_id, "notice_kind": metadata["notice_kind"],
                           "previous_document_id": metadata["previous_document_id"],
                           "previous_period": metadata["previous_periods"].get(item.series_id)})
    return sorted(result, key=lambda r: (r["period"], r["observed_at"], r["series_id"]), reverse=True)[:limit]
