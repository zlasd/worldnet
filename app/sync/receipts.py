"""Durable, signed import receipts; never acknowledge before database commit."""

from __future__ import annotations

import hmac
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.sync.transfer import SyncError, _sign


def safe_batch_id(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value):
        raise SyncError("sync batch_id is invalid")
    return value


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.part")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def receipt_path(directory: Path, batch_id: str) -> Path:
    return directory / f"{safe_batch_id(batch_id)}.json"


def make_receipt(batch: dict, *, secret: str, status: str, counts: dict | None = None) -> dict:
    payload = {
        "kind": "worldnet-import-receipt-v1",
        "batch_id": safe_batch_id(batch["payload"]["batch_id"]),
        "batch_signature": batch["signature"],
        "source_instance": batch["payload"]["source_instance"],
        "status": status,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "counts": counts or {},
    }
    return {"payload": payload, "signature": _sign(payload, secret)}


def verify_receipt(receipt: dict, batch: dict, *, secret: str) -> dict:
    payload = receipt.get("payload")
    signature = receipt.get("signature")
    if not isinstance(payload, dict) or not isinstance(signature, str):
        raise SyncError("invalid import receipt")
    if not hmac.compare_digest(signature, _sign(payload, secret)):
        raise SyncError("invalid receipt signature")
    if (
        payload.get("kind") != "worldnet-import-receipt-v1"
        or payload.get("batch_id") != batch["payload"]["batch_id"]
        or payload.get("source_instance") != batch["payload"]["source_instance"]
        or payload.get("batch_signature") != batch["signature"]
        or payload.get("status") not in {"imported", "failed"}
    ):
        raise SyncError("receipt does not match batch")
    return payload
