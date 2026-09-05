#!/usr/bin/env python3
"""Push or retry one signed sync batch and check its import receipt."""

from __future__ import annotations

import json
import os
from pathlib import Path

from app.db.session import get_db_session
from app.sync.client import CurlTransport, run_once
from app.sync.transfer import build_batch


def main() -> int:
    secret = os.environ.get("WORLDNET_SYNC_SECRET", "")
    source = os.environ.get("WORLDNET_SYNC_SOURCE_INSTANCE", "oci-overseas")
    try:
        transport = CurlTransport(
            url=os.environ.get("WORLDNET_SYNC_URL", ""),
            pin=os.environ.get("WORLDNET_SYNC_TLS_PIN", ""),
            secret=secret,
            source_instance=source,
            timeout=int(os.environ.get("WORLDNET_SYNC_HTTP_TIMEOUT_SECONDS", "120")),
        )

        def export(**windows):
            with get_db_session() as session:
                return build_batch(session, secret=secret, source_instance=source, **windows)

        result = run_once(
            Path(os.environ.get("WORLDNET_SYNC_CONTAINER_DIRECTORY", "/var/lib/worldnet-sync")),
            secret=secret,
            source_instance=source,
            exporter=export,
            transport=transport,
            overlap_seconds=int(os.environ.get("WORLDNET_SYNC_OVERLAP_SECONDS", "300")),
        )
        print(json.dumps(result))
    except Exception as exc:
        # Do not print arbitrary database/HTTP exception text into service logs.
        print(f"sync push failed: {type(exc).__name__}; batch retained for retry")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
