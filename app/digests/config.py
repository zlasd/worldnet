from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class DigestWindowConfig(BaseModel):
    mode: Literal["since_last_run"] = "since_last_run"
    first_run_fallback: Literal["previous_day"] = "previous_day"


class DigestSelectionConfig(BaseModel):
    max_candidates: int = Field(default=50, gt=0)
    max_items: int = Field(default=10, gt=0)
    priorities: list[str] = Field(default_factory=lambda: ["p1", "p2"])
    include_watchlist_only: bool = False


class DigestLlmConfig(BaseModel):
    enabled: bool = True
    max_retries: int = Field(default=1, ge=0)
    user_prompt: str | None = None


class DigestRenderingConfig(BaseModel):
    title: str = "WorldNet 重要事项日报"
    include_empty_digest: bool = False


class DigestTaskConfig(BaseModel):
    window: DigestWindowConfig = Field(default_factory=DigestWindowConfig)
    selection: DigestSelectionConfig = Field(default_factory=DigestSelectionConfig)
    llm: DigestLlmConfig = Field(default_factory=DigestLlmConfig)
    rendering: DigestRenderingConfig = Field(default_factory=DigestRenderingConfig)


def parse_digest_task_config(data: dict[str, Any] | None) -> DigestTaskConfig:
    return DigestTaskConfig.model_validate(data or {})
