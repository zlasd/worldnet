from app.pipelines import runner


class _FakeAdapter:
    source_name = "fake_source"


def test_run_full_pipeline_does_not_prepare_notifications(monkeypatch):
    monkeypatch.setattr(runner, "ingest_documents", lambda adapter, session: ["doc-1"])
    monkeypatch.setattr(runner, "dedupe_documents", lambda session: (1, 0))
    monkeypatch.setattr(runner, "run_entity_matching", lambda session: 1)
    monkeypatch.setattr(runner, "normalize_events", lambda session: ["event-1"])

    result = runner.run_full_pipeline(_FakeAdapter(), object())

    assert result == {
        "ingested": 1,
        "deduped": 0,
        "entity_matches": 1,
        "events_created": 1,
        "notifications_prepared": 0,
    }
