from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Reading(BaseModel):
    model_config = ConfigDict(extra="forbid")

    series_id: str
    name: str
    period: str
    value: Decimal | None
    status: Literal["available", "unavailable"] = "available"
    unit: str
    adjustment: Literal["SA", "NSA", "unspecified"] = "unspecified"
    basis: str = "官方公布值"
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def finite_value(self):
        if (self.value is None) != (self.status == "unavailable"):
            raise ValueError("Missing values require an explicit unavailable status")
        if self.value is not None and not self.value.is_finite():
            raise ValueError("A macro observation must be a finite number")
        return self


class Release(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["nbs", "pbc", "bls", "bea", "fed"]
    country: Literal["CN", "US"]
    group: str
    period: str
    title: str
    source_url: str
    published_at: datetime | None = None
    published_date: date | None = None
    publication_note: str = ""
    readings: list[Reading] = Field(default_factory=list)
    kind: Literal["data", "policy"] = "data"
    text: str = ""
    vintage: str = ""

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.group}:{self.period}"

    @model_validator(mode="after")
    def validate_release(self):
        expected_country = "CN" if self.provider in {"nbs", "pbc"} else "US"
        if self.country != expected_country:
            raise ValueError("Provider country mismatch")
        if not self.source_url.startswith("https://"):
            raise ValueError("An official HTTPS source is required")
        if self.published_at is not None and self.published_at.tzinfo is None:
            raise ValueError("Published timestamps must have an explicit timezone")
        identities = [(r.series_id, r.period) for r in self.readings]
        if len(identities) != len(set(identities)):
            raise ValueError("Duplicate observations in a release")
        if not self.readings and (self.kind != "policy" or not self.text.strip()):
            raise ValueError("No actual observations or policy statement were parsed")
        return self


class DataConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    providers: list[Literal["nbs", "pbc", "bls", "bea", "fed"]] = Field(
        default_factory=lambda: ["nbs", "pbc"]
    )
    title: str = "WorldNet 宏观数据公布值与央行政策"
    standalone_notifications: bool = False
    notification_max_age_days: int = Field(default=3, ge=1, le=14)
