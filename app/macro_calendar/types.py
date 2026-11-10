from datetime import date, datetime, time, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CalendarRelease(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["nbs", "bls", "bea", "fed"]
    key: str
    title: str
    country: Literal["CN", "US"]
    release_date: date | None
    release_time: time | None = None
    timezone: str
    source_url: str
    status: Literal["scheduled", "postponed", "cancelled"] = "scheduled"

    @model_validator(mode="after")
    def validate_release(self):
        ZoneInfo(self.timezone)
        if self.status == "scheduled" and self.release_date is None:
            raise ValueError("A scheduled release requires an official date")
        if self.release_time and self.release_time.tzinfo:
            raise ValueError("release_time uses the separately specified timezone")
        if not self.source_url.startswith("https://"):
            raise ValueError("An official HTTPS calendar URL is required")
        return self

    def instant(self) -> datetime | None:
        if self.release_date is None or self.release_time is None:
            return None
        return datetime.combine(
            self.release_date, self.release_time, ZoneInfo(self.timezone)
        ).astimezone(timezone.utc)

    def display_date(self, display_timezone: str) -> date | None:
        instant = self.instant()
        return instant.astimezone(ZoneInfo(display_timezone)).date() if instant else self.release_date

    def is_past(self, now: datetime) -> bool:
        instant = self.instant()
        if instant:
            return instant <= now
        return self.release_date is not None and self.release_date < now.astimezone(
            ZoneInfo(self.timezone)
        ).date()


class CalendarConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    providers: list[Literal["nbs", "bls", "bea", "fed"]] = Field(
        default_factory=lambda: ["nbs"]
    )
    lead_days: int = Field(default=7, ge=1, le=30)
    display_timezone: str = "Asia/Shanghai"
    max_stale_hours: int = Field(default=48, ge=1, le=168)
    title: str = "WorldNet 宏观数据与央行日程预告"
    standalone_notifications: bool = False

    @model_validator(mode="after")
    def validate_timezone(self):
        ZoneInfo(self.display_timezone)
        return self
