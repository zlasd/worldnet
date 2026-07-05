from app.api.routes.watchlists import list_watchlist_items
from app.models.instrument import Instrument
from app.models.watchlist import Watchlist, WatchlistItem


def test_list_watchlist_items_returns_instrument_payload(session):
    instrument = Instrument(
        market="CN",
        exchange="SSE",
        ticker="600519",
        company_name="贵州茅台",
        currency="CNY",
    )
    watchlist = Watchlist(name="A股观察")
    session.add_all([instrument, watchlist])
    session.flush()
    item = WatchlistItem(
        watchlist_id=watchlist.watchlist_id,
        instrument_id=instrument.instrument_id,
        priority="high",
        is_holding=True,
    )
    session.add(item)
    session.flush()

    payload = list_watchlist_items("A股观察", db=session)

    assert len(payload) == 1
    assert payload[0]["priority"] == "high"
    assert payload[0]["instrument"].ticker == "600519"
