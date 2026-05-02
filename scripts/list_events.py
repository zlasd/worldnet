#!/usr/bin/env python3
"""List recent events."""
import sys

sys.path.insert(0, ".")

from app.db.session import get_db_session
from app.models.normalized_event import NormalizedEvent

if __name__ == "__main__":
    with get_db_session() as session:
        events = (
            session.query(NormalizedEvent)
            .order_by(NormalizedEvent.created_at.desc())
            .limit(20)
            .all()
        )
        rows = [(e.severity, e.event_type, e.title) for e in events]

    print(f"Recent events ({len(rows)}):")
    for severity, event_type, title in rows:
        title_preview = title[:60] + "..." if len(title) > 60 else title
        print(f"  [{severity.upper()}] {event_type} | {title_preview}")
