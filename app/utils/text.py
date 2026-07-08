from __future__ import annotations

import re

from bs4 import BeautifulSoup


def clean_text(raw_text: str | None) -> str:
    if not raw_text:
        return ""
    text = BeautifulSoup(raw_text, "html.parser").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()


def summarize_text(raw_text: str | None, max_length: int = 500) -> str | None:
    text = clean_text(raw_text)
    if not text:
        return None
    if len(text) <= max_length:
        return text
    return f"{text[:max_length].rstrip()}..."
