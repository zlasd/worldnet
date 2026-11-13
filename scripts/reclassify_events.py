"""Preview or repair derived news classifications in an explicit UTC window."""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.session import get_db_session  # noqa: E402
from app.pipelines.reclassify import reclassify_events  # noqa: E402


def utc_datetime(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise argparse.ArgumentTypeError("include an explicit timezone, e.g. 2026-11-12T00:00:00Z")
    return result.astimezone(timezone.utc).replace(tzinfo=None)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", type=utc_datetime, required=True)
    parser.add_argument("--until", type=utc_datetime, required=True)
    parser.add_argument("--apply", action="store_true", help="write changes; otherwise preview only")
    args = parser.parse_args()
    with get_db_session() as session:
        result = reclassify_events(session, since=args.since, until=args.until, apply=args.apply)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
