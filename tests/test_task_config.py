from pathlib import Path

import pytest

from app.tasks.task_config import load_task_definitions


def _write_task_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def test_load_task_definitions_merges_default_and_custom_directories(tmp_path):
    default_dir = tmp_path / "default"
    custom_dir = tmp_path / "custom"

    _write_task_file(
        default_dir / "builtins.yaml",
        """
        tasks:
          - task_id: rsshub-sse-watchlist-disclosure
            enabled: true
            source: rsshub_sse_disclosure
            interval_minutes: 5
            selector:
              watchlist_only: true
              market: CN
              exchange: SSE
          - task_id: worldnewsapi-top-news
            enabled: false
            source: worldnewsapi_top_news
            interval_minutes: 30
        """,
    )
    _write_task_file(
        custom_dir / "overrides.yaml",
        """
        tasks:
          - task_id: rsshub-sse-watchlist-disclosure
            enabled: false
          - task_id: worldnewsapi-top-news
            enabled: true
        """,
    )

    tasks = load_task_definitions(default_dir=default_dir, custom_dir=custom_dir)

    assert [task.task_id for task in tasks] == ["worldnewsapi-top-news"]
    assert tasks[0].source == "worldnewsapi_top_news"
    assert tasks[0].interval_minutes == 30


def test_load_task_definitions_validates_schedule_fields(tmp_path):
    default_dir = tmp_path / "default"
    custom_dir = tmp_path / "custom"
    _write_task_file(
        default_dir / "invalid.yaml",
        """
        tasks:
          - task_id: bad-task
            enabled: true
            source: rsshub_cls_telegraph
        """,
    )

    with pytest.raises(ValueError, match="exactly one of interval_minutes or cron"):
        load_task_definitions(default_dir=default_dir, custom_dir=custom_dir)
