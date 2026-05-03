from app.tasks.scheduler import (
    ScheduledJob,
    ScheduledSource,
    build_scheduler_jobs,
    run_scheduler_cycle,
)


def test_build_scheduler_jobs_starts_enabled_sources_immediately(monkeypatch):
    monkeypatch.setattr(
        "app.tasks.scheduler.get_scheduled_sources",
        lambda: [
            ScheduledSource("rsshub_cls_telegraph", 5),
            ScheduledSource("rsshub_cls_depth", 30),
        ],
    )

    jobs = build_scheduler_jobs(start_time=100.0)

    assert jobs == [
        ScheduledJob("rsshub_cls_telegraph", 300.0, 100.0),
        ScheduledJob("rsshub_cls_depth", 1800.0, 100.0),
    ]


def test_run_scheduler_cycle_runs_due_jobs_and_reschedules():
    jobs = [
        ScheduledJob("rsshub_cls_telegraph", 300.0, 10.0),
        ScheduledJob("rsshub_cls_depth", 1800.0, 50.0),
    ]
    ran = []

    run_scheduler_cycle(jobs=jobs, now=50.0, runner=lambda source: ran.append(source) or {})

    assert ran == ["rsshub_cls_telegraph", "rsshub_cls_depth"]
    assert jobs[0].next_run_at == 350.0
    assert jobs[1].next_run_at == 1850.0


def test_run_scheduler_cycle_skips_not_due_jobs():
    jobs = [ScheduledJob("rsshub_cls_telegraph", 300.0, 100.0)]

    run_scheduler_cycle(jobs=jobs, now=50.0, runner=lambda source: {"unexpected": source})

    assert jobs[0].next_run_at == 100.0
