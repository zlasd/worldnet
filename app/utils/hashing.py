import hashlib


def compute_content_hash(title: str, raw_text: str = "") -> str:
    content = f"{title.strip()}\n{raw_text.strip()}"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def compute_canonical_hash(title: str) -> str:
    normalized = " ".join(title.lower().strip().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
