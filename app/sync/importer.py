"""Import a file transactionally, then publish its durable receipt."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from app.sync.receipts import atomic_json, make_receipt, receipt_path
from app.sync.transfer import import_batch, read_batch, verify_batch


def import_file(
    path: Path,
    *,
    session_factory: Callable,
    secret: str,
    expected_source_instance: str,
    receipts_dir: Path,
    archive_dir: Path | None = None,
) -> dict:
    batch = read_batch(path)
    payload = verify_batch(batch, secret=secret, expected_source_instance=expected_source_instance)
    destination = receipt_path(receipts_dir, payload["batch_id"])
    try:
        with session_factory() as session:
            counts = import_batch(
                session, batch, secret=secret, expected_source_instance=expected_source_instance
            )
    except Exception:
        # Generic status only: database errors may contain SQL, source text or credentials.
        atomic_json(destination, make_receipt(batch, secret=secret, status="failed"))
        raise
    # If this write fails after commit, the inbox file remains and the next run
    # re-imports idempotently before issuing the missing receipt.
    atomic_json(destination, make_receipt(batch, secret=secret, status="imported", counts=counts))
    if archive_dir is not None:
        archive_dir.mkdir(parents=True, exist_ok=True)
        path.replace(archive_dir / path.name)
    return counts
