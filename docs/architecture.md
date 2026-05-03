# WorldNet Stock Radar — Architecture Overview

## System Overview

WorldNet is a personal stock news/announcement event radar. It ingests raw news and official announcements, matches them to tracked instruments, normalizes them into structured events, and prepares prioritized notifications.

## Pipeline Flow

```
Source (RSS / Official Announcements / RSSHub CLS / World News API Top News)
        │
        ▼
[1] Ingest  →  source_document  (raw, content_hash, canonical_hash)
        │
        ▼
[2] Dedupe  →  mark duplicates (content_hash / canonical_hash)
        │
        ▼
[3] Entity Match  →  document_entity_match  (ticker / name / alias)
        │
        ▼
[4] Normalize  →  normalized_event  (event_type, severity, sentiment, actionability)
        │
        ▼
[5] Prioritize  →  P1 / P2 / P3 based on severity + watchlist membership
        │
        ▼
[6] Notification  →  notification_log  (status=skipped until channel configured)
```

## Data Models

| Model | Purpose |
|---|---|
| `Instrument` | Tracked stock (ticker, market, aliases) |
| `Watchlist` / `WatchlistItem` | User-defined watch lists |
| `SourceDocument` | Raw fetched document |
| `DocumentEntityMatch` | Document ↔ Instrument link |
| `NormalizedEvent` | Structured, classified event |
| `EventImpact` | Per-instrument impact assessment |
| `NotificationLog` | Outbound notification record |

## Key Classification Rules

- **Event type**: keyword matching on title + body (see `app/rules/keyword_rules.py`)
- **Severity**: `CRITICAL` for halts/delisting/investigations; `HIGH` for earnings warnings etc. from official sources
- **Actionability**: `IMMEDIATE` (critical/high + official), `MONITOR` (medium), `DIGEST_ONLY` (low)
- **Notification priority**: P1 = official + critical/high + in watchlist; P2 = medium; P3 = everything else

## Tech Stack

- **FastAPI** — REST API
- **SQLAlchemy 2.x** (synchronous) + **SQLite** — persistence
- **Pydantic v2** — schema validation
- **httpx** — HTTP client for adapters
- **BeautifulSoup4** — RSS/HTML parsing

## World News API Integration Notes

- `worldnewsapi_top_news` is an aggregator-tier news source.
- Each Top News cluster is flattened into individual `SourceDocument` rows.
- Cluster context is preserved in `SourceDocument.metadata` for downstream debugging and dedupe analysis.
- The intended operating cadence is one request every 30 minutes, which fits within a 50 requests/day quota with minimal headroom.

## RSSHub Integration Notes

- RSSHub routes are treated as route-level RSS sources instead of a separate parsing pipeline.
- `rsshub_cls_telegraph` maps to `/cls/telegraph` and is intended for a 5-minute polling cadence.
- `rsshub_cls_depth` maps to `/cls/depth` and is intended for a 30-minute polling cadence.
- Route metadata such as `rsshub_path`, `rsshub_route`, and `upstream_source` is preserved in `SourceDocument.metadata`.
- The project exposes route-specific enable flags and poll interval configuration, but external infrastructure is still responsible for actual scheduling.

## Running Locally

```bash
pip install -e ".[dev]"
python scripts/init_db.py
python scripts/seed_data.py
python scripts/run_pipeline.py
python scripts/list_events.py
uvicorn app.api.main:app --reload
pytest tests/ -v
```
