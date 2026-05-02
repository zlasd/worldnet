from sqlalchemy.orm import Session

from app.models.normalized_event import NormalizedEvent
from app.models.watchlist import WatchlistItem
from app.rules.priority_rules import determine_notification_priority


def prioritize_events(session: Session) -> list[tuple[NormalizedEvent, str]]:
    watchlist_ids = {
        item.instrument_id for item in session.query(WatchlistItem).all()
    }

    recent_events = (
        session.query(NormalizedEvent)
        .filter_by(is_duplicate=False)
        .order_by(NormalizedEvent.created_at.desc())
        .limit(100)
        .all()
    )

    results = []
    for event in recent_events:
        priority = determine_notification_priority(event, watchlist_ids)
        results.append((event, priority))

    return results
