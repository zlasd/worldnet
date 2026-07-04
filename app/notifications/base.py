from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class NotificationPayload:
    event_id: str
    title: str
    body: str | None
    priority: str
    instrument_id: str | None
    dedupe_key: str

    @property
    def message_body(self) -> str:
        content = self.body.strip() if self.body else "No summary provided."
        return f"{self.title}\n\n{content}"


@dataclass(frozen=True)
class NotificationResult:
    ok: bool
    error: str | None = None


class Notifier(Protocol):
    outlet_id: str
    channel: str

    def send(self, payload: NotificationPayload) -> NotificationResult:
        ...
