from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class DigestCandidate:
    event_id: str
    title: str
    summary: str | None
    priority: str
    event_type: str
    severity: str
    actionability: str
    source_tier: str | None
    detected_at: datetime
    event_time: datetime | None
    instrument_id: str | None


@dataclass(frozen=True)
class DigestSelectedItem:
    event_id: str
    rank: int
    priority: str
    title: str
    why_it_matters: str
    suggested_action: str


@dataclass(frozen=True)
class DigestSelectionResult:
    summary: str
    items: list[DigestSelectedItem]
    used_llm: bool
    error: str | None = None


@dataclass(frozen=True)
class DigestDispatchPayload:
    digest_type: str
    window_start: datetime
    window_end: datetime
    title: str
    body: str
    items: list[DigestSelectedItem]
    last_error: str | None = None


@dataclass(frozen=True)
class DigestMessagePayload:
    title: str
    body: str | None

    @property
    def message_body(self) -> str:
        content = self.body.strip() if self.body else "No digest content."
        return f"{self.title}\n\n{content}"
