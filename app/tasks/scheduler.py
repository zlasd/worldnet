from __future__ import annotations

import signal
import time
from dataclasses import dataclass
from datetime import datetime
from threading import Event
from typing import Any, Callable
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db_session
from app.digests.runner import run_digest
from app.models.instrument import Instrument
from app.models.watchlist import Watchlist, WatchlistItem
from app.tasks.pipeline_task import run_pipeline
from app.tasks.task_config import TaskDefinition, load_task_definitions
from app.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class ExpandedTask:
    job_id: str
    task: TaskDefinition
    source_config: dict[str, Any]
    description: str


@dataclass
class ScheduledJob:
    expanded_task: ExpandedTask
    next_run_at: float | None = None
    last_triggered_slot: str | None = None


def get_scheduler_timezone() -> ZoneInfo:
    return ZoneInfo(settings.scheduler_timezone)


def _cron_weekday(dt: datetime) -> int:
    return (dt.weekday() + 1) % 7


def _parse_cron_value(token: str, minimum: int, maximum: int) -> set[int]:
    values: set[int] = set()
    for part in token.split(","):
        part = part.strip()
        if not part:
            raise ValueError("Empty cron field component.")

        if "/" in part:
            range_part, step_part = part.split("/", 1)
            step = int(step_part)
            if step <= 0:
                raise ValueError("Cron step must be greater than 0.")
        else:
            range_part = part
            step = 1

        if range_part == "*":
            start, end = minimum, maximum
        elif "-" in range_part:
            start_str, end_str = range_part.split("-", 1)
            start, end = int(start_str), int(end_str)
        else:
            start = end = int(range_part)

        if start < minimum or end > maximum or start > end:
            raise ValueError(f"Cron value '{part}' is outside the allowed range {minimum}-{maximum}.")

        values.update(range(start, end + 1, step))
    return values


def cron_matches(expression: str, current_time: datetime) -> bool:
    fields = expression.split()
    if len(fields) != 5:
        raise ValueError("Cron expression must contain 5 fields.")

    minute, hour, day, month, weekday = fields
    checks = (
        (minute, current_time.minute, 0, 59),
        (hour, current_time.hour, 0, 23),
        (month, current_time.month, 1, 12),
    )
    for token, value, minimum, maximum in checks:
        values = _parse_cron_value(token, minimum, maximum)
        if value not in values:
            return False

    day_values = _parse_cron_value(day, 1, 31)
    weekday_values = _parse_cron_value(weekday, 0, 7)
    if 7 in weekday_values:
        weekday_values.add(0)

    day_matches = current_time.day in day_values
    weekday_matches = _cron_weekday(current_time) in weekday_values
    if day == "*" and weekday == "*":
        return True
    if day == "*":
        return weekday_matches
    if weekday == "*":
        return day_matches
    return day_matches or weekday_matches


def _requires_instrument_expansion(task: TaskDefinition) -> bool:
    if task.kind != "pipeline":
        return False
    return any(
        [
            task.selector.watchlist_only,
            task.selector.market is not None,
            task.selector.exchange is not None,
        ]
    )


def select_instruments_for_task(session: Session, task: TaskDefinition) -> list[Instrument]:
    query = session.query(Instrument).filter(Instrument.is_active.is_(True))
    if task.selector.watchlist_only:
        query = (
            query.join(WatchlistItem, WatchlistItem.instrument_id == Instrument.instrument_id)
            .join(Watchlist, Watchlist.watchlist_id == WatchlistItem.watchlist_id)
            .filter(Watchlist.is_active.is_(True))
        )
    if task.selector.market:
        query = query.filter(Instrument.market == task.selector.market)
    if task.selector.exchange:
        query = query.filter(Instrument.exchange == task.selector.exchange)
    return query.distinct().all()


def _build_instrument_source_config(
    source: str | None,
    instrument: Instrument,
    base_config: dict[str, Any],
) -> dict[str, Any]:
    source_config = dict(base_config)
    instrument_metadata = {
        "company_name": instrument.company_name,
        "local_name": instrument.local_name,
    }
    if source == "rsshub_sse_disclosure":
        return {
            **source_config,
            "product_id": instrument.ticker,
            **instrument_metadata,
        }
    if source == "rsshub_szse_listed_notice":
        return {
            **source_config,
            "stock": instrument.ticker,
            **instrument_metadata,
        }
    return source_config


def expand_task(task: TaskDefinition, session: Session) -> list[ExpandedTask]:
    if not _requires_instrument_expansion(task):
        return [
            ExpandedTask(
                job_id=task.task_id,
                task=task,
                source_config=dict(task.source_config),
                description=task.description or task.task_id,
            )
        ]

    instruments = select_instruments_for_task(session, task)
    expanded_tasks: list[ExpandedTask] = []
    for instrument in instruments:
        expanded_tasks.append(
            ExpandedTask(
                job_id=f"{task.task_id}:{instrument.instrument_id}",
                task=task,
                source_config=_build_instrument_source_config(
                    task.source,
                    instrument,
                    task.source_config,
                ),
                description=f"{task.task_id} ({instrument.exchange}:{instrument.ticker})",
            )
        )
    return expanded_tasks


def sync_scheduler_jobs(
    task_definitions: list[TaskDefinition],
    existing_jobs: dict[str, ScheduledJob],
    start_time: float,
    session_factory: Callable[[], Any] = get_db_session,
) -> dict[str, ScheduledJob]:
    expanded_tasks: dict[str, ExpandedTask] = {}
    with session_factory() as session:
        for task in task_definitions:
            for expanded_task in expand_task(task, session):
                expanded_tasks[expanded_task.job_id] = expanded_task

    synced_jobs: dict[str, ScheduledJob] = {}
    for job_id, expanded_task in expanded_tasks.items():
        existing_job = existing_jobs.get(job_id)
        if existing_job:
            existing_job.expanded_task = expanded_task
            synced_jobs[job_id] = existing_job
            continue

        synced_jobs[job_id] = ScheduledJob(
            expanded_task=expanded_task,
            next_run_at=start_time if expanded_task.task.interval_minutes is not None else None,
        )
    return synced_jobs


def _current_cron_slot(current_time: datetime) -> str:
    return current_time.strftime("%Y-%m-%dT%H:%M")


def run_scheduler_cycle(
    jobs: dict[str, ScheduledJob],
    now_monotonic: float,
    now_datetime: datetime,
    runner: Callable[[str, dict[str, Any] | None], dict[str, dict]] = run_pipeline,
    digest_runner: Callable[[str, dict[str, Any] | None], dict[str, Any]] = run_digest,
) -> list[str]:
    ran_jobs: list[str] = []
    for job in jobs.values():
        task = job.expanded_task.task
        should_run = False
        cron_slot = None

        if task.interval_minutes is not None:
            should_run = job.next_run_at is not None and now_monotonic >= job.next_run_at
        else:
            cron_slot = _current_cron_slot(now_datetime)
            should_run = cron_matches(task.cron or "", now_datetime) and job.last_triggered_slot != cron_slot

        if not should_run:
            continue

        logger.info("Running scheduled task=%s kind=%s", job.expanded_task.description, task.kind)
        try:
            if task.kind == "digest":
                digest_runner(task.digest_type or "", job.expanded_task.source_config or None)
            else:
                runner(task.source or "", job.expanded_task.source_config or None)
            ran_jobs.append(job.expanded_task.job_id)
        except Exception:
            logger.exception(
                "Scheduled task failed for task=%s kind=%s",
                job.expanded_task.description,
                task.kind,
            )
        finally:
            if task.interval_minutes is not None:
                job.next_run_at = now_monotonic + (task.interval_minutes * 60.0)
            else:
                job.last_triggered_slot = cron_slot
    return ran_jobs


def run_scheduler(
    stop_event: Event | None = None,
    runner: Callable[[str, dict[str, Any] | None], dict[str, dict]] = run_pipeline,
    digest_runner: Callable[[str, dict[str, Any] | None], dict[str, Any]] = run_digest,
    now_fn: Callable[[], float] = time.monotonic,
    now_datetime_fn: Callable[[], datetime] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    session_factory: Callable[[], Any] = get_db_session,
    max_cycles: int | None = None,
) -> None:
    if not settings.scheduler_enabled:
        logger.info("Scheduler is disabled via configuration.")
        return

    timezone = get_scheduler_timezone()
    now_datetime_fn = now_datetime_fn or (lambda: datetime.now(timezone))
    jobs: dict[str, ScheduledJob] = {}
    cycles = 0

    while True:
        if stop_event and stop_event.is_set():
            logger.info("Stop signal received. Exiting scheduler.")
            return

        now_monotonic = now_fn()
        task_definitions = load_task_definitions()
        if not task_definitions and not jobs:
            logger.warning("No enabled tasks were found. Scheduler will idle.")
        jobs = sync_scheduler_jobs(
            task_definitions=task_definitions,
            existing_jobs=jobs,
            start_time=now_monotonic,
            session_factory=session_factory,
        )
        run_scheduler_cycle(
            jobs=jobs,
            now_monotonic=now_monotonic,
            now_datetime=now_datetime_fn(),
            runner=runner,
            digest_runner=digest_runner,
        )
        cycles += 1

        if max_cycles is not None and cycles >= max_cycles:
            return

        sleep_fn(settings.scheduler_tick_seconds)


def install_signal_handlers(stop_event: Event) -> None:
    def _handle_signal(signum, _frame) -> None:
        logger.info("Received signal %s, stopping scheduler.", signum)
        stop_event.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)


def main() -> None:
    stop_event = Event()
    install_signal_handlers(stop_event)
    run_scheduler(stop_event=stop_event)


if __name__ == "__main__":
    main()
