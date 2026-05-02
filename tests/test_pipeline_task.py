from contextlib import contextmanager

from app.tasks import pipeline_task


class _FakeAdapter:
    def __init__(self, source_name):
        self.source_name = source_name


@contextmanager
def _fake_session():
    yield object()


def test_run_pipeline_handles_all_sources(monkeypatch):
    def fake_build_adapters(source):
        assert source == "all"
        return [_FakeAdapter("official_announcement"), _FakeAdapter("worldnewsapi_top_news")]

    def fake_run_full_pipeline(adapter, session):
        assert session is not None
        return {"ingested": len(adapter.source_name)}

    monkeypatch.setattr(pipeline_task, "build_adapters", fake_build_adapters)
    monkeypatch.setattr(pipeline_task, "get_db_session", _fake_session)
    monkeypatch.setattr(pipeline_task, "run_full_pipeline", fake_run_full_pipeline)

    result = pipeline_task.run_pipeline("all")

    assert result == {
        "official_announcement": {"ingested": len("official_announcement")},
        "worldnewsapi_top_news": {"ingested": len("worldnewsapi_top_news")},
    }


def test_run_worldnewsapi_pipeline_returns_single_source_result(monkeypatch):
    monkeypatch.setattr(
        pipeline_task,
        "run_pipeline",
        lambda source: {source: {"ingested": 3}},
    )

    result = pipeline_task.run_worldnewsapi_pipeline()

    assert result == {"ingested": 3}
