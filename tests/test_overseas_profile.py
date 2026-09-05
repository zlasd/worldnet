from pathlib import Path

from app.tasks.task_config import load_task_definitions


def test_overseas_profile_has_no_mainland_news_tasks():
    tasks = load_task_definitions(
        default_dir=Path("config/tasks/default"),
        custom_dir=Path("config/tasks/overseas"),
    )

    pipeline_tasks = [task for task in tasks if task.kind == "pipeline"]
    assert pipeline_tasks
    assert {task.source for task in pipeline_tasks} == {"rss_news"}
    assert all(
        task.source_config["metadata"]["topic"] in {"economy", "politics"}
        for task in pipeline_tasks
    )
    assert {task.source_config["metadata"]["publisher"] for task in pipeline_tasks} == {
        "Bloomberg",
        "Wall Street Journal",
        "BBC",
    }


def test_overseas_profile_generates_a_local_only_digest():
    tasks = load_task_definitions(
        default_dir=Path("config/tasks/default"),
        custom_dir=Path("config/tasks/overseas"),
    )

    digest = next(task for task in tasks if task.task_id == "daily-important-digest")
    assert digest.source_config["rendering"]["title"] == "WorldNet 海外经济政治日报"
    assert digest.source_config["rendering"]["include_empty_digest"] is True
    assert digest.source_config["llm"]["enabled"] is False
    assert digest.source_config["market_sections"]["index_futures_basis"]["enabled"] is False
