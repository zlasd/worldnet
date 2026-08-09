from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class DigestWindowConfig(BaseModel):
    mode: Literal["since_last_run"] = "since_last_run"
    first_run_fallback: Literal["previous_day"] = "previous_day"


class DigestSelectionConfig(BaseModel):
    max_candidates: int = Field(default=50, gt=0)
    max_items: int = Field(default=10, gt=0)
    priorities: list[str] = Field(default_factory=lambda: ["p1", "p2", "p3"])
    include_watchlist_only: bool = False


class DigestLlmConfig(BaseModel):
    enabled: bool = True
    max_retries: int = Field(default=1, ge=0)
    user_prompt: str | None = None


class DigestRenderingConfig(BaseModel):
    title: str = "WorldNet 重要事项日报"
    include_empty_digest: bool = False


class IndexFuturesBasisConfig(BaseModel):
    enabled: bool = False
    products: list[Literal["IF", "IH", "IC", "IM"]] = Field(
        default_factory=lambda: ["IF", "IH", "IC", "IM"]
    )
    history_days: int = Field(default=252, ge=20, le=1000)
    lookback_calendar_days: int = Field(default=15, ge=1, le=60)


class DigestMarketSectionsConfig(BaseModel):
    index_futures_basis: IndexFuturesBasisConfig = Field(default_factory=IndexFuturesBasisConfig)


class PaperStrategyConfig(BaseModel):
    enabled: bool = True
    initial_nav: float = Field(default=1_000_000.0, gt=0)
    minimum_days_to_expiry: int = Field(default=10, ge=1)
    transaction_cost_bps: float = Field(default=5.0, ge=0)
    switch_threshold_annualized: float = Field(default=0.02, ge=0)


class MarketCommentaryLlmConfig(BaseModel):
    enabled: bool = True
    max_retries: int = Field(default=1, ge=0, le=5)


class MarketCommentaryConfig(BaseModel):
    enabled: bool = True
    llm: MarketCommentaryLlmConfig = Field(default_factory=MarketCommentaryLlmConfig)


class DigestTaskConfig(BaseModel):
    window: DigestWindowConfig = Field(default_factory=DigestWindowConfig)
    selection: DigestSelectionConfig = Field(default_factory=DigestSelectionConfig)
    llm: DigestLlmConfig = Field(default_factory=DigestLlmConfig)
    rendering: DigestRenderingConfig = Field(default_factory=DigestRenderingConfig)
    market_sections: DigestMarketSectionsConfig = Field(default_factory=DigestMarketSectionsConfig)
    paper_strategy: PaperStrategyConfig = Field(default_factory=PaperStrategyConfig)
    market_commentary: MarketCommentaryConfig = Field(default_factory=MarketCommentaryConfig)


def parse_digest_task_config(data: dict[str, Any] | None) -> DigestTaskConfig:
    return DigestTaskConfig.model_validate(data or {})
