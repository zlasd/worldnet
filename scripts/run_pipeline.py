#!/usr/bin/env python3
"""Run the full pipeline."""
import sys

sys.path.insert(0, ".")

from app.adapters.official_announcement_adapter import OfficialAnnouncementAdapter
from app.db.session import get_db_session
from app.pipelines.runner import run_full_pipeline

if __name__ == "__main__":
    adapter = OfficialAnnouncementAdapter()
    with get_db_session() as session:
        result = run_full_pipeline(adapter, session)
    print("Pipeline complete:")
    for k, v in result.items():
        print(f"  {k}: {v}")
