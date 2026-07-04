from contextlib import contextmanager
from datetime import datetime

from app.models.instrument import Instrument
from app.models.watchlist import Watchlist, WatchlistItem
from app.tasks.scheduler import (
    ExpandedTask,
    ScheduledJob,
    cron_matches,
    run_scheduler_cycle,
    sync_scheduler_jobs,
)
from app.tasks.task_config import TaskDefinition


@contextmanager
def _session_factory(session):
    yield session


def _make_instrument(
    ticker: str,
    exchange: str,
    company_name: str,
    market: str = "CN",
    is_active: bool = True,
) -> Instrument:
    return Instrument(
        market=market,
        ticker=ticker,
        exchange=exchange,
        company_name=company_name,
        local_name=company_name,
        currency="CNY",
        is_active=is_active,
    )


def test_sync_scheduler_jobs_expands_watchlist_a_share_tasks(session):
    sse_instrument = _make_instrument("600000", "SSE", "浦发银行")
    szse_instrument = _make_instrument("000001", "SZSE", "平安银行")
    session.add_all([sse_instrument, szse_instrument])
    session.flush()

    watchlist = Watchlist(name="A股观察", is_active=True)
    session.add(watchlist)
    session.flush()
    session.add(
        WatchlistItem(
            watchlist_id=watchlist.watchlist_id,
            instrument_id=sse_instrument.instrument_id,
        )
    )
    session.flush()

    task = TaskDefinition.model_validate(
        {
            "task_id": "rsshub-sse-watchlist-disclosure",
            "source": "rsshub_sse_disclosure",
            "interval_minutes": 5,
            "selector": {
                "watchlist_only": True,
                "market": "CN",
                "exchange": "SSE",
            },
        }
    )

    jobs = sync_scheduler_jobs(
        task_definitions=[task],
        existing_jobs={},
        start_time=100.0,
        session_factory=lambda: _session_factory(session),
    )

    assert list(jobs) == [f"rsshub-sse-watchlist-disclosure:{sse_instrument.instrument_id}"]
    job = next(iter(jobs.values()))
    assert job.expanded_task.source_config == {
        "product_id": "600000",
        "company_name": "浦发银行",
        "local_name": "浦发银行",
    }
    assert job.next_run_at == 100.0


def test_run_scheduler_cycle_runs_interval_jobs_and_reschedules():
    task = TaskDefinition.model_validate(
        {
            "task_id": "rsshub-cls-telegraph",
            "source": "rsshub_cls_telegraph",
            "interval_minutes": 5,
        }
    )
    jobs = {
        "rsshub-cls-telegraph": ScheduledJob(
            expanded_task=ExpandedTask(
                job_id="rsshub-cls-telegraph",
                task=task,
                source_config={},
                description="财联社电报监控",
            ),
            next_run_at=10.0,
        )
    }
    ran = []

    run_scheduler_cycle(
        jobs=jobs,
        now_monotonic=10.0,
        now_datetime=datetime(2024, 1, 1, 10, 0),
        runner=lambda source, source_config=None: ran.append((source, source_config)) or {},
    )

    assert ran == [("rsshub_cls_telegraph", None)]
    assert jobs["rsshub-cls-telegraph"].next_run_at == 310.0


def test_run_scheduler_cycle_runs_cron_tasks_once_per_matching_slot():
    task = TaskDefinition.model_validate(
        {
            "task_id": "rsshub-sse-watchlist-disclosure",
            "source": "rsshub_sse_disclosure",
            "cron": "*/5 * * * *",
        }
    )
    jobs = {
        "rsshub-sse-watchlist-disclosure": ScheduledJob(
            expanded_task=ExpandedTask(
                job_id="rsshub-sse-watchlist-disclosure",
                task=task,
                source_config={"product_id": "600000"},
                description="上交所公告监控",
            )
        )
    }
    ran = []

    run_scheduler_cycle(
        jobs=jobs,
        now_monotonic=10.0,
        now_datetime=datetime(2024, 1, 1, 10, 5),
        runner=lambda source, source_config=None: ran.append((source, source_config)) or {},
    )
    run_scheduler_cycle(
        jobs=jobs,
        now_monotonic=12.0,
        now_datetime=datetime(2024, 1, 1, 10, 5, 30),
        runner=lambda source, source_config=None: ran.append((source, source_config)) or {},
    )

    assert ran == [("rsshub_sse_disclosure", {"product_id": "600000"})]


def test_run_scheduler_cycle_dispatches_digest_tasks():
    task = TaskDefinition.model_validate(
        {
            "task_id": "daily-important-digest",
            "kind": "digest",
            "digest_type": "important_daily",
            "cron": "30 7 * * *",
            "source_config": {"selection": {"max_items": 5}},
        }
    )
    jobs = {
        "daily-important-digest": ScheduledJob(
            expanded_task=ExpandedTask(
                job_id="daily-important-digest",
                task=task,
                source_config=task.source_config,
                description="WorldNet 重要事项日报",
            )
        )
    }
    pipeline_runs = []
    digest_runs = []

    run_scheduler_cycle(
        jobs=jobs,
        now_monotonic=10.0,
        now_datetime=datetime(2024, 1, 1, 7, 30),
        runner=lambda source, source_config=None: pipeline_runs.append((source, source_config)) or {},
        digest_runner=lambda digest_type, task_config=None: digest_runs.append(
            (digest_type, task_config)
        )
        or {},
    )

    assert pipeline_runs == []
    assert digest_runs == [("important_daily", {"selection": {"max_items": 5}})]


def test_cron_matches_supports_steps_lists_and_ranges():
    assert cron_matches("*/5 9-15 * * 1-5", datetime(2024, 1, 1, 10, 10))
    assert cron_matches("0,30 9 * * 1", datetime(2024, 1, 1, 9, 30))
    assert not cron_matches("*/5 9-15 * * 1-5", datetime(2024, 1, 1, 10, 11))


def test_cron_matches_uses_day_or_weekday_when_both_are_restricted():
    assert cron_matches("0 10 2 * 1", datetime(2024, 1, 1, 10, 0))
    assert cron_matches("0 10 2 * 1", datetime(2024, 1, 2, 10, 0))
    assert not cron_matches("0 10 2 * 1", datetime(2024, 1, 3, 10, 0))
