#!/usr/bin/env python3
"""Export a signed overseas-to-domestic WorldNet sync batch."""

from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone
from pathlib import Path

from app.db.session import get_db_session
from app.sync.transfer import build_batch, write_batch


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="gzip JSON output path")
    parser.add_argument("--secret-env", default="WORLDNET_SYNC_SECRET")
    parser.add_argument("--source-instance", default="oci-overseas")
    parser.add_argument("--since", help="inclusive ISO-8601 observed_at timestamp")
    parser.add_argument("--until", help="exclusive ISO-8601 observed_at timestamp")
    parser.add_argument(
        "--digest-since", help="inclusive digest updated_at cursor; omitted to backfill all digests"
    )
    parser.add_argument(
        "--digest-until", help="exclusive digest updated_at cursor; defaults to --until"
    )
    args = parser.parse_args()
    secret = os.environ.get(args.secret_env, "")
    if not secret:
        parser.error(f"environment variable {args.secret_env} is empty")

    with get_db_session() as session:
        batch = build_batch(
            session,
            secret=secret,
            source_instance=args.source_instance,
            since=_parse_datetime(args.since),
            until=_parse_datetime(args.until),
            digest_since=_parse_datetime(args.digest_since),
            digest_until=_parse_datetime(args.digest_until),
        )
    path = write_batch(batch, Path(args.output))
    print(f"exported batch {batch['payload']['batch_id']} to {path}")
    print(
        f"documents={len(batch['payload']['documents'])} events={len(batch['payload']['events'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
