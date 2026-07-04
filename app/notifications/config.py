from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator

from app.core.config import settings

NotificationOutletType = Literal["qq_agent_mail", "hermes_send"]


class NotificationOutletDefinition(BaseModel):
    outlet_id: str
    type: NotificationOutletType
    enabled: bool = True
    channel: str | None = None
    description: str | None = None
    recipients: str | None = None
    target: str | None = None
    command: str | None = None
    timeout_seconds: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_outlet_id(self) -> "NotificationOutletDefinition":
        if not self.outlet_id.strip():
            raise ValueError("outlet_id cannot be empty.")
        return self


def _iter_notification_files(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    return sorted(directory.glob("*.yaml")) + sorted(directory.glob("*.yml"))


def _read_notification_file(path: Path) -> list[dict[str, Any]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(
            f"Notification config file '{path}' must contain a mapping at the top level."
        )

    outlets = data.get("outlets", [])
    if not isinstance(outlets, list):
        raise ValueError(f"Notification config file '{path}' must define 'outlets' as a list.")

    normalized_outlets: list[dict[str, Any]] = []
    for item in outlets:
        if not isinstance(item, dict):
            raise ValueError(
                f"Notification config file '{path}' contains a non-mapping outlet entry."
            )
        normalized_outlets.append(item)
    return normalized_outlets


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


def load_notification_outlets(
    default_dir: str | Path | None = None,
    custom_dir: str | Path | None = None,
) -> list[NotificationOutletDefinition]:
    default_path = Path(default_dir or settings.notification_config_default_dir)
    custom_path = Path(custom_dir or settings.notification_config_custom_dir)

    merged_outlets: dict[str, dict[str, Any]] = {}
    for path in [*_iter_notification_files(default_path), *_iter_notification_files(custom_path)]:
        for outlet_data in _read_notification_file(path):
            outlet_id = outlet_data.get("outlet_id")
            if not isinstance(outlet_id, str) or not outlet_id.strip():
                raise ValueError(
                    f"Notification config file '{path}' contains an outlet without a valid outlet_id."
                )
            existing = merged_outlets.get(outlet_id, {})
            merged_outlets[outlet_id] = _merge_dict(existing, outlet_data)

    definitions: list[NotificationOutletDefinition] = []
    for outlet_id in sorted(merged_outlets):
        outlet_data = merged_outlets[outlet_id]
        if outlet_data.get("enabled") is False:
            continue
        definitions.append(NotificationOutletDefinition.model_validate(outlet_data))
    return definitions
