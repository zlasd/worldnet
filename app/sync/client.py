"""Restart-safe sender: retain a batch until a signed import receipt arrives."""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from app.sync.receipts import atomic_json, safe_batch_id, verify_receipt
from app.sync.transfer import SyncError, read_batch, verify_batch, write_batch


def _timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (
        result.replace(tzinfo=timezone.utc)
        if result.tzinfo is None
        else result.astimezone(timezone.utc)
    )


class CurlTransport:
    """Use curl's SPKI pinning, without placing the bearer secret in argv."""

    def __init__(
        self, *, url: str, pin: str, secret: str, source_instance: str, timeout: int = 120
    ):
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or not parsed.path.endswith("/upload")
        ):
            raise SyncError(
                "sync URL must be an HTTPS /upload endpoint without credentials or query"
            )
        if not re.fullmatch(r"sha256//[A-Za-z0-9+/]{43}=", pin):
            raise SyncError("sync TLS pin must be a SHA256 SPKI pin")
        if not secret or any(c in secret + source_instance for c in "\r\n"):
            raise SyncError("invalid sync credentials or source instance")
        self.url, self.pin, self.secret, self.source_instance = url, pin, secret, source_instance
        self.timeout = timeout

    def __call__(self, method: str, batch_id: str, path: Path | None = None) -> dict:
        safe_batch_id(batch_id)
        url = self.url if method == "POST" else self.url[: -len("upload")] + "batches/" + batch_id
        with tempfile.TemporaryDirectory(prefix="worldnet-sync-") as temp:
            headers = Path(temp) / "headers"
            headers.write_text(
                f"Authorization: Bearer {self.secret}\nX-WorldNet-Source-Instance: {self.source_instance}\n"
                f"X-WorldNet-Batch-Id: {batch_id}\nContent-Type: application/gzip\n"
            )
            headers.chmod(0o600)
            args = [
                "curl",
                "--fail",
                "--silent",
                "--show-error",
                "--proto",
                "=https",
                "--connect-timeout",
                "10",
                "--max-time",
                str(self.timeout),
                "--retry",
                "3",
                "--retry-delay",
                "2",
                "--retry-connrefused",
                "--insecure",
                "--pinnedpubkey",
                self.pin,
                "--header",
                f"@{headers}",
            ]
            if method == "POST":
                if path is None:
                    raise SyncError("upload file is missing")
                args.extend(["--data-binary", f"@{path}"])
            result = subprocess.run(
                [*args, url], capture_output=True, timeout=self.timeout * 4 + 60
            )
        if result.returncode:
            raise SyncError(f"sync HTTPS request failed (curl exit {result.returncode})")
        try:
            response = json.loads(result.stdout)
        except ValueError as exc:
            raise SyncError("invalid sync HTTPS response") from exc
        if not isinstance(response, dict):
            raise SyncError("sync HTTPS response must be an object")
        return response


def run_once(
    directory: Path,
    *,
    secret: str,
    source_instance: str,
    exporter: Callable,
    transport: Callable,
    now: datetime | None = None,
    overlap_seconds: int = 300,
) -> dict:
    """Run under the host push lock; at most one new batch per invocation.

    Two durable cursors only advance after import. Overlap compensates for
    ordinary clock/commit lag; explicit historical export can repair older gaps.
    """
    if overlap_seconds < 0:
        raise SyncError("sync overlap must not be negative")
    now = now or datetime.now(timezone.utc)
    now = now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now.astimezone(timezone.utc)
    outbox, sent = directory / "outbox", directory / "sent"
    outbox.mkdir(parents=True, exist_ok=True)
    sent.mkdir(parents=True, exist_ok=True)
    state_file = directory / "cursors.json"
    state = json.loads(state_file.read_text()) if state_file.exists() else {}
    if not isinstance(state, dict):
        raise SyncError("invalid sync cursor state")
    legacy = directory / "last_successful_export"
    if not state and legacy.exists():
        state["document_until"] = legacy.read_text().strip()
        # Old senders never tracked digests separately: backfill them once.
    paths = sorted(outbox.glob("*.json.gz"))
    if not paths:
        if any(
            _timestamp(state.get(k)) and _timestamp(state[k]) >= now
            for k in ("document_until", "digest_until")
        ):
            return {"status": "idle"}

        def start(key):
            value = _timestamp(state.get(key))
            return value - timedelta(seconds=overlap_seconds) if value else None

        batch = exporter(
            since=start("document_until"),
            until=now,
            digest_since=start("digest_until"),
            digest_until=now,
            advance_cursors=True,
        )
        verify_batch(batch, secret=secret, expected_source_instance=source_instance)
        batch_id = safe_batch_id(batch["payload"]["batch_id"])
        path = write_batch(batch, outbox / f"batch-{batch_id}.json.gz")
        paths = [path]
    completed = []
    for path in paths:
        batch = read_batch(path)
        payload = verify_batch(batch, secret=secret, expected_source_instance=source_instance)
        batch_id = safe_batch_id(payload["batch_id"])
        response = transport("POST", batch_id, path)
        if response.get("batch_id") != batch_id or response.get("status") not in {
            "accepted",
            "already_present",
            "imported",
        }:
            raise SyncError("unexpected upload acknowledgement")
        receipt = transport("GET", batch_id)
        if receipt.get("status") == "pending" and receipt.get("batch_id") == batch_id:
            return {"status": "pending", "batch_id": batch_id, "imported": completed}
        result = verify_receipt(receipt, batch, secret=secret)
        if result["status"] != "imported":
            raise SyncError("remote import failed; pending batch retained for retry")
        for key, field in (("document_until", "window_end"), ("digest_until", "digest_window_end")):
            value = _timestamp(payload.get(field))
            previous = _timestamp(state.get(key))
            if (
                payload.get("advance_cursors") is True
                and value
                and (previous is None or value > previous)
            ):
                state[key] = value.isoformat()
        # Persist cursor first. If archive fails, repeat the exact acknowledged
        # batch next time; the receiver receipt prevents duplicate ingestion.
        atomic_json(state_file, state)
        atomic_json(sent / f"receipt-{batch_id}.json", receipt)
        path.replace(sent / path.name)
        completed.append(batch_id)
    return {"status": "imported", "batches": completed}
