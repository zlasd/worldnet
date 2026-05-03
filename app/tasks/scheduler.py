import signal
import time
from dataclasses import dataclass
from threading import Event
from typing import Callable

from app.core.config import settings
from app.tasks.pipeline_task import run_pipeline
from app.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class ScheduledSource:
    source: str
    interval_minutes: int


@dataclass
class ScheduledJob:
    source: str
    interval_seconds: float
    next_run_at: float


def get_scheduled_sources() -> list[ScheduledSource]:
    sources: list[ScheduledSource] = []
    if settings.rsshub_cls_telegraph_enabled:
        sources.append(
            ScheduledSource(
                source="rsshub_cls_telegraph",
                interval_minutes=settings.rsshub_cls_telegraph_poll_interval_minutes,
            )
        )
    if settings.rsshub_cls_depth_enabled:
        sources.append(
            ScheduledSource(
                source="rsshub_cls_depth",
                interval_minutes=settings.rsshub_cls_depth_poll_interval_minutes,
            )
        )
    if settings.worldnewsapi_enabled:
        sources.append(
            ScheduledSource(
                source="worldnewsapi_top_news",
                interval_minutes=settings.worldnewsapi_poll_interval_minutes,
            )
        )
    return sources


def build_scheduler_jobs(start_time: float) -> list[ScheduledJob]:
    return [
        ScheduledJob(
            source=scheduled_source.source,
            interval_seconds=scheduled_source.interval_minutes * 60.0,
            next_run_at=start_time,
        )
        for scheduled_source in get_scheduled_sources()
    ]


def run_scheduler_cycle(
    jobs: list[ScheduledJob],
    now: float,
    runner: Callable[[str], dict[str, dict]] = run_pipeline,
) -> None:
    for job in jobs:
        if now < job.next_run_at:
            continue

        logger.info("Running scheduled pipeline for source=%s", job.source)
        try:
            runner(job.source)
        except Exception:
            logger.exception("Scheduled pipeline failed for source=%s", job.source)
        finally:
            job.next_run_at = now + job.interval_seconds


def run_scheduler(
    stop_event: Event | None = None,
    runner: Callable[[str], dict[str, dict]] = run_pipeline,
    now_fn: Callable[[], float] = time.monotonic,
    sleep_fn: Callable[[float], None] = time.sleep,
    max_cycles: int | None = None,
) -> None:
    if not settings.scheduler_enabled:
        logger.info("Scheduler is disabled via configuration.")
        return

    jobs = build_scheduler_jobs(start_time=now_fn())
    if not jobs:
        logger.warning("No scheduled sources are enabled. Scheduler will idle.")

    cycles = 0
    while True:
        if stop_event and stop_event.is_set():
            logger.info("Stop signal received. Exiting scheduler.")
            return

        run_scheduler_cycle(jobs=jobs, now=now_fn(), runner=runner)
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
