from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator

from app.core.config import settings


class TaskSelector(BaseModel):
    watchlist_only: bool = False
    market: str | None = None
    exchange: str | None = None


class TaskDefinition(BaseModel):
    task_id: str
    kind: Literal["pipeline", "digest"] = "pipeline"
    source: str | None = None
    digest_type: str | None = None
    enabled: bool = True
    interval_minutes: int | None = None
    cron: str | None = None
    description: str | None = None
    selector: TaskSelector = Field(default_factory=TaskSelector)
    source_config: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_schedule(self) -> "TaskDefinition":
        has_interval = self.interval_minutes is not None
        has_cron = self.cron is not None
        if has_interval == has_cron:
            raise ValueError("Task must define exactly one of interval_minutes or cron.")
        if self.interval_minutes is not None and self.interval_minutes <= 0:
            raise ValueError("interval_minutes must be greater than 0.")
        if self.kind == "pipeline" and not self.source:
            raise ValueError("Pipeline task must define source.")
        if self.kind == "digest" and not self.digest_type:
            raise ValueError("Digest task must define digest_type.")
        return self


def _iter_task_files(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    return sorted(directory.glob("*.yaml")) + sorted(directory.glob("*.yml"))


def _read_task_file(path: Path) -> list[dict[str, Any]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Task config file '{path}' must contain a mapping at the top level.")

    tasks = data.get("tasks", [])
    if not isinstance(tasks, list):
        raise ValueError(f"Task config file '{path}' must define 'tasks' as a list.")

    normalized_tasks: list[dict[str, Any]] = []
    for item in tasks:
        if not isinstance(item, dict):
            raise ValueError(f"Task config file '{path}' contains a non-mapping task entry.")
        normalized_tasks.append(item)
    return normalized_tasks


def _merge_dict(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if value is None:
            continue
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_task_definitions(
    default_dir: str | Path | None = None,
    custom_dir: str | Path | None = None,
) -> list[TaskDefinition]:
    default_path = Path(default_dir or settings.scheduler_tasks_default_dir)
    custom_path = Path(custom_dir or settings.scheduler_tasks_custom_dir)

    merged_tasks: dict[str, dict[str, Any]] = {}
    for path in [*_iter_task_files(default_path), *_iter_task_files(custom_path)]:
        for task_data in _read_task_file(path):
            task_id = task_data.get("task_id")
            if not isinstance(task_id, str) or not task_id.strip():
                raise ValueError(f"Task config file '{path}' contains a task without a valid task_id.")
            existing = merged_tasks.get(task_id, {})
            merged_tasks[task_id] = _merge_dict(existing, task_data)

    definitions: list[TaskDefinition] = []
    for task_id in sorted(merged_tasks):
        task_data = merged_tasks[task_id]
        if task_data.get("enabled") is False:
            continue
        definitions.append(TaskDefinition.model_validate(task_data))
    return definitions
