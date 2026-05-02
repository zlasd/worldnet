from sqlalchemy.orm import Session

from app.models.instrument import Instrument


def get_instruments(
    session: Session,
    market: str | None = None,
    ticker: str | None = None,
    limit: int = 50,
) -> list[Instrument]:
    q = session.query(Instrument).filter_by(is_active=True)
    if market:
        q = q.filter(Instrument.market == market)
    if ticker:
        q = q.filter(Instrument.ticker == ticker)
    return q.limit(limit).all()


def get_instrument_by_id(session: Session, instrument_id: str) -> Instrument | None:
    return session.get(Instrument, instrument_id)
