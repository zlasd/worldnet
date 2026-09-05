"""Small HTTPS receiver for signed overseas-to-domestic sync batches.

The receiver only authenticates and atomically places batches in the local
inbox.  A separate systemd timer runs the database importer, keeping the
public HTTPS process away from the database credentials and import code path.
"""

from __future__ import annotations

import hmac
import os
import re
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, status

from app.sync.transfer import SyncError, read_batch, verify_batch

_BATCH_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
_DEFAULT_INBOX = "/var/lib/worldnet-sync/inbox"
_DEFAULT_SOURCE_INSTANCE = "oci-overseas"
_DEFAULT_MAX_UPLOAD_BYTES = 16 * 1024 * 1024

app = FastAPI(title="WorldNet sync receiver", version="1")


def _settings() -> tuple[str, str, Path, int]:
    secret = os.environ.get("WORLDNET_SYNC_SECRET", "")
    source_instance = os.environ.get(
        "WORLDNET_SYNC_SOURCE_INSTANCE", _DEFAULT_SOURCE_INSTANCE
    )
    inbox = Path(os.environ.get("WORLDNET_SYNC_INBOX_DIRECTORY", _DEFAULT_INBOX))
    try:
        max_upload_bytes = int(
            os.environ.get(
                "WORLDNET_SYNC_RECEIVER_MAX_BYTES", str(_DEFAULT_MAX_UPLOAD_BYTES)
            )
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
        secret
        and scheme.lower() == "bearer"
        and hmac.compare_digest(provided.strip(), secret)
    )


def _safe_batch_id(value: object) -> str:
    batch_id = str(value or "")
    if not _BATCH_ID_RE.fullmatch(batch_id):
        raise SyncError("sync batch_id is invalid")
    return batch_id


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload(request: Request) -> dict[str, str]:
    secret, expected_source_instance, inbox, max_upload_bytes = _settings()
    if not _authorized(request, secret):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing sync credentials.",
        )

    if request.headers.get("x-worldnet-source-instance") != expected_source_instance:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Unexpected sync source instance.",
        )

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
        batch_id = _safe_batch_id(payload.get("batch_id"))
        header_batch_id = request.headers.get("x-worldnet-batch-id")
        if header_batch_id and not hmac.compare_digest(header_batch_id, batch_id):
            raise SyncError("sync batch_id header does not match payload")

        final_path = inbox / f"batch-{batch_id}.json.gz"
        if final_path.exists():
            temporary_path.unlink(missing_ok=True)
            return {"status": "already_present", "batch_id": batch_id}
        temporary_path.replace(final_path)
        return {"status": "accepted", "batch_id": batch_id}
    except HTTPException:
        temporary_path.unlink(missing_ok=True)
        raise
    except (OSError, SyncError, ValueError) as exc:
        temporary_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid sync batch: {exc}",
        ) from exc
