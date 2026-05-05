#!/usr/bin/env python3
"""Run the full pipeline."""
import argparse
import sys

sys.path.insert(0, ".")

from app.adapters.factory import DEFAULT_SOURCE, PIPELINE_SOURCE_CHOICES
from app.tasks.pipeline_task import run_pipeline


def _parse_source_options(options: list[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for option in options:
        if "=" not in option:
            raise ValueError(f"Invalid --source-option '{option}'. Expected key=value.")
        key, value = option.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            raise ValueError(f"Invalid --source-option '{option}'. Key cannot be empty.")
        parsed[key] = value
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser(description="Run ingestion pipelines for selected source(s).")
    parser.add_argument(
        "--source",
        choices=PIPELINE_SOURCE_CHOICES,
        default=DEFAULT_SOURCE,
        help="Source to run. Use 'all' to run every configured adapter sequentially.",
    )
    parser.add_argument(
        "--source-option",
        action="append",
        default=[],
        help="Pass adapter options as key=value. Can be used multiple times.",
    )
    args = parser.parse_args()

    source_config = _parse_source_options(args.source_option)
    if args.source == "all" and source_config:
        raise ValueError("--source-option is not supported when --source=all.")

    results = run_pipeline(args.source, source_config=source_config or None)

    print("Pipeline complete:")
    for source_name, result in results.items():
        print(f"{source_name}:")
        for key, value in result.items():
            print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
