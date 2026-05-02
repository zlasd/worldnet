import re


def truncate(text: str, max_len: int = 200) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len].rstrip() + "..."


def normalize_whitespace(text: str) -> str:
    return " ".join(text.split())


def extract_ticker_mentions(text: str) -> list[str]:
    """Extract potential ticker symbols from text (e.g. $AAPL, (AAPL))."""
    pattern = r'\$([A-Z]{1,5})\b|\(([A-Z]{1,5})\)'
    matches = re.findall(pattern, text)
    return [m[0] or m[1] for m in matches]
