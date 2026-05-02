from sqlalchemy.orm import Session

from app.models.normalized_event import NormalizedEvent


def get_events(
    session: Session,
    severity: str | None = None,
    event_type: str | None = None,
    limit: int = 50,
) -> list[NormalizedEvent]:
    q = session.query(NormalizedEvent)
    if severity:
        q = q.filter(NormalizedEvent.severity == severity)
    if event_type:
        q = q.filter(NormalizedEvent.event_type == event_type)
    return q.order_by(NormalizedEvent.created_at.desc()).limit(limit).all()
