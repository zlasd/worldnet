#!/usr/bin/env python3
"""Run the full pipeline."""
import argparse
import sys

sys.path.insert(0, ".")

from app.adapters.factory import DEFAULT_SOURCE, PIPELINE_SOURCE_CHOICES, build_adapters
from app.db.session import get_db_session
from app.pipelines.runner import run_full_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Run ingestion pipelines for selected source(s).")
    parser.add_argument(
        "--source",
        choices=PIPELINE_SOURCE_CHOICES,
        default=DEFAULT_SOURCE,
        help="Source to run. Use 'all' to run every configured adapter sequentially.",
    )
    args = parser.parse_args()

    results: dict[str, dict] = {}
    for adapter in build_adapters(args.source):
        with get_db_session() as session:
            results[adapter.source_name] = run_full_pipeline(adapter, session)

    print("Pipeline complete:")
    for source_name, result in results.items():
        print(f"{source_name}:")
        for key, value in result.items():
            print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
