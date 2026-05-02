from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RawDocument:
    title: str
    url: str | None
    author: str | None
    published_at: str | None  # ISO string or None
    raw_text: str
    language: str = "en"
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseAdapter(ABC):
    source_name: str
    source_type: str
    source_tier: str

    @abstractmethod
    def fetch(self) -> list[dict[str, Any]]:
        """Fetch raw data from source."""
        ...

    @abstractmethod
    def parse(self, raw_data: list[dict[str, Any]]) -> list[RawDocument]:
        """Parse raw data into RawDocument objects."""
        ...

    def normalize_metadata(self, doc: RawDocument) -> dict[str, Any]:
        return {
            "source_name": self.source_name,
            "source_type": self.source_type,
            "source_tier": self.source_tier,
            **(doc.metadata or {}),
        }

    def run(self) -> list[RawDocument]:
        raw = self.fetch()
        return self.parse(raw)
