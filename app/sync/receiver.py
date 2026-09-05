"""Small HTTPS receiver for signed overseas-to-domestic sync batches.

The receiver only authenticates and atomically places batches in the local
inbox.  A separate systemd timer runs the database importer, keeping the
public HTTPS process away from the database credentials and import code path.
"""

from __future__ import annotations

import hmac
import json
import os
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, status

from app.sync.receipts import receipt_path, safe_batch_id, verify_receipt
from app.sync.transfer import SyncError, read_batch, verify_batch

_DEFAULT_INBOX = "/var/lib/worldnet-sync/inbox"
_DEFAULT_SOURCE_INSTANCE = "oci-overseas"
_DEFAULT_MAX_UPLOAD_BYTES = 16 * 1024 * 1024

app = FastAPI(title="WorldNet sync receiver", version="1")


def _settings() -> tuple[str, str, Path, int]:
    secret = os.environ.get("WORLDNET_SYNC_SECRET", "")
    source_instance = os.environ.get("WORLDNET_SYNC_SOURCE_INSTANCE", _DEFAULT_SOURCE_INSTANCE)
    inbox = Path(os.environ.get("WORLDNET_SYNC_INBOX_DIRECTORY", _DEFAULT_INBOX))
    try:
        max_upload_bytes = int(
            os.environ.get("WORLDNET_SYNC_RECEIVER_MAX_BYTES", str(_DEFAULT_MAX_UPLOAD_BYTES))
        )
    except ValueError as exc:
        raise RuntimeError("WORLDNET_SYNC_RECEIVER_MAX_BYTES must be an integer") from exc
    if max_upload_bytes <= 0:
        raise RuntimeError("WORLDNET_SYNC_RECEIVER_MAX_BYTES must be positive")
    return secret, source_instance, inbox, max_upload_bytes


def _authorized(request: Request, secret: str) -> bool:
    authorization = request.headers.get("authorization", "")
    scheme, _, provided = authorization.partition(" ")
    return bool(
        secret and scheme.lower() == "bearer" and hmac.compare_digest(provided.strip(), secret)
    )


def _authenticate(request: Request) -> tuple[str, str, Path, int]:
    config = _settings()
    secret, source, _, _ = config
    if not _authorized(request, secret):
        raise HTTPException(status_code=401, detail="Invalid or missing sync credentials.")
    if request.headers.get("x-worldnet-source-instance") != source:
        raise HTTPException(status_code=403, detail="Unexpected sync source instance.")
    return config


def _receipts_dir(inbox: Path) -> Path:
    return Path(os.environ.get("WORLDNET_SYNC_RECEIPTS_DIRECTORY", str(inbox.parent / "receipts")))


@app.get("/batches/{batch_id}")
async def batch_status(batch_id: str, request: Request) -> dict:
    secret, source, inbox, _ = _authenticate(request)
    try:
        path = receipt_path(_receipts_dir(inbox), batch_id)
        if path.exists():
            receipt = json.loads(path.read_text())
            # Authenticate stored receipts before exposing them. The client
            # additionally compares the batch signature to its pending file.
            payload = receipt["payload"]
            batch = {
                "payload": {"batch_id": batch_id, "source_instance": source},
                "signature": payload["batch_signature"],
            }
            verify_receipt(receipt, batch, secret=secret)
            return receipt
        return {"status": "pending", "batch_id": safe_batch_id(batch_id)}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid sync status.") from exc


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload(request: Request) -> dict[str, str]:
    secret, expected_source_instance, inbox, max_upload_bytes = _authenticate(request)

    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > max_upload_bytes:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail="Sync batch is too large.",
                )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid Content-Length.",
            ) from exc

    inbox.mkdir(parents=True, exist_ok=True)
    upload_id = uuid4().hex
    temporary_path = inbox / f".upload-{upload_id}.part"
    try:
        total = 0
        with temporary_path.open("xb") as handle:
            async for chunk in request.stream():
                total += len(chunk)
                if total > max_upload_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail="Sync batch is too large.",
                    )
                handle.write(chunk)

        batch = read_batch(temporary_path)
        payload = verify_batch(
            batch,
            secret=secret,
            expected_source_instance=expected_source_instance,
        )
        batch_id = safe_batch_id(payload.get("batch_id"))
        header_batch_id = request.headers.get("x-worldnet-batch-id")
        if header_batch_id and not hmac.compare_digest(header_batch_id, batch_id):
            raise SyncError("sync batch_id header does not match payload")

        receipt_file = receipt_path(_receipts_dir(inbox), batch_id)
        if receipt_file.exists():
            receipt = json.loads(receipt_file.read_text())
            result = verify_receipt(receipt, batch, secret=secret)
            if result["status"] == "imported":
                return {"status": "imported", "batch_id": batch_id}
        final_path = inbox / f"batch-{batch_id}.json.gz"
        try:
            # Atomic create without replacing an in-flight file for this ID.
            os.link(temporary_path, final_path)
        except FileExistsError:
            existing = read_batch(final_path)
            verify_batch(existing, secret=secret, expected_source_instance=expected_source_instance)
            if existing["signature"] != batch["signature"]:
                raise HTTPException(
                    status_code=409, detail="Batch ID already has different content."
                )
            return {"status": "already_present", "batch_id": batch_id}
        return {"status": "accepted", "batch_id": batch_id}
    except HTTPException:
        temporary_path.unlink(missing_ok=True)
        raise
    except (OSError, SyncError, ValueError, KeyError, TypeError) as exc:
        temporary_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid sync batch.",
        ) from exc
    finally:
        temporary_path.unlink(missing_ok=True)
