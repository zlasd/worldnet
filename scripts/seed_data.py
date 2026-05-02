#!/usr/bin/env python3
"""Seed sample instruments and watchlist."""
import json
import sys

sys.path.insert(0, ".")

from app.db.session import get_db_session
from app.models.instrument import Instrument
from app.models.watchlist import Watchlist, WatchlistItem

SAMPLE_INSTRUMENTS = [
    {
        "market": "US",
        "ticker": "AAPL",
        "exchange": "NASDAQ",
        "company_name": "Apple Inc.",
        "local_name": None,
        "aliases": json.dumps(["Apple", "苹果"]),
        "sector": "Technology",
        "industry": "Consumer Electronics",
        "currency": "USD",
    },
    {
        "market": "HK",
        "ticker": "0700",
        "exchange": "HKEX",
        "company_name": "Tencent Holdings Limited",
        "local_name": "腾讯控股有限公司",
        "aliases": json.dumps(["腾讯", "Tencent"]),
        "sector": "Technology",
        "industry": "Internet Services",
        "currency": "HKD",
    },
    {
        "market": "CN",
        "ticker": "600519",
        "exchange": "SSE",
        "company_name": "Kweichow Moutai Co., Ltd.",
        "local_name": "贵州茅台酒股份有限公司",
        "aliases": json.dumps(["茅台", "Moutai", "贵州茅台"]),
        "sector": "Consumer Staples",
        "industry": "Beverages",
        "currency": "CNY",
    },
]

if __name__ == "__main__":
    with get_db_session() as session:
        instruments = []
        for data in SAMPLE_INSTRUMENTS:
            existing = session.query(Instrument).filter_by(ticker=data["ticker"]).first()
            if existing:
                print(f"  Instrument {data['ticker']} already exists, skipping.")
                instruments.append(existing)
                continue
            instr = Instrument(**data)
            session.add(instr)
            session.flush()
            instruments.append(instr)
            print(f"  Created instrument: {data['ticker']} - {data['company_name']}")

        existing_watchlist = session.query(Watchlist).filter_by(name="My Watchlist").first()
        if not existing_watchlist:
            wl = Watchlist(name="My Watchlist", description="Default watchlist")
            session.add(wl)
            session.flush()

            for instr in instruments:
                item = WatchlistItem(
                    watchlist_id=wl.watchlist_id,
                    instrument_id=instr.instrument_id,
                    priority="high",
                    is_holding=True,
                )
                session.add(item)

            print(f"  Created watchlist: {wl.name} with {len(instruments)} items.")
        else:
            print("  Watchlist already exists, skipping.")

    print("Seed data complete.")
