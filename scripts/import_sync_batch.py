#!/usr/bin/env python3
"""Verify and import signed WorldNet sync batches from an inbox."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from app.db.session import get_db_session
from app.sync.transfer import SyncError, import_batch, read_batch


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", help=".json.gz batch files")
    parser.add_argument("--secret-env", default="WORLDNET_SYNC_SECRET")
    parser.add_argument("--expected-source-instance", default="oci-overseas")
    parser.add_argument(
        "--archive-dir",
        help="move successfully imported batches here; leave unset to keep files in place",
    )
    args = parser.parse_args()
    secret = os.environ.get(args.secret_env, "")
    if not secret:
        parser.error(f"environment variable {args.secret_env} is empty")
    archive_dir = Path(args.archive_dir) if args.archive_dir else None
    if archive_dir:
        archive_dir.mkdir(parents=True, exist_ok=True)

    failures = 0
    for raw_path in args.paths:
        path = Path(raw_path)
        try:
            batch = read_batch(path)
            with get_db_session() as session:
                counts = import_batch(
                    session,
                    batch,
                    secret=secret,
                    expected_source_instance=args.expected_source_instance,
                )
            print(f"imported batch {counts['batch_id']} from {path}: {counts}")
            if archive_dir:
                path.rename(archive_dir / path.name)
        except (OSError, SyncError) as exc:
            failures += 1
            print(f"failed to import {path}: {exc}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
