# worldnet

Personal stock news/announcement event radar — fetches, classifies, and prioritizes market events for tracked instruments.

## Quick Start

```bash
pip install -e ".[dev]"
python scripts/init_db.py      # create DB tables
python scripts/seed_data.py    # seed sample instruments & watchlist
python scripts/run_pipeline.py # run official announcement pipeline
python scripts/run_pipeline.py --source rsshub_cls_telegraph
python scripts/run_pipeline.py --source rsshub_cls_depth
python scripts/run_pipeline.py --source worldnewsapi_top_news
python scripts/list_events.py  # view recent events
uvicorn app.api.main:app --reload  # start API server
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/instruments/` | List tracked instruments |
| GET | `/documents/` | List source documents |
| GET | `/events/` | List normalized events |
| GET | `/watchlists/` | List watchlists |

## Pipeline Stages

1. **Ingest** — fetch raw documents from adapters (RSS, official announcements, RSSHub CLS, World News API Top News)
2. **Dedupe** — detect duplicate content by hash
3. **Entity Match** — link documents to instruments (ticker / name / alias)
4. **Normalize** — classify event type, sentiment, severity
5. **Prioritize** — P1/P2/P3 based on severity + watchlist membership
6. **Notification** — log notification records

## RSSHub CLS Routes

Set these environment variables before running RSSHub-backed sources:

```bash
export RSSHUB_BASE_URL=http://localhost:1200
export RSSHUB_CLS_TELEGRAPH_ENABLED=true
export RSSHUB_CLS_TELEGRAPH_POLL_INTERVAL_MINUTES=5
export RSSHUB_CLS_DEPTH_ENABLED=true
export RSSHUB_CLS_DEPTH_POLL_INTERVAL_MINUTES=30
```

Available RSSHub CLS sources:

- `rsshub_cls_telegraph` -> `/cls/telegraph`
- `rsshub_cls_depth` -> `/cls/depth`

The project keeps route-specific enable flags and poll interval settings, but actual scheduling is still expected to happen outside this repository.

## World News API Top News

Set these environment variables before running `--source worldnewsapi_top_news`:

```bash
export WORLDNEWSAPI_API_KEY=your_api_key
export WORLDNEWSAPI_SOURCE_COUNTRY=us
export WORLDNEWSAPI_LANGUAGE=en
export WORLDNEWSAPI_HEADLINES_ONLY=false
```

The adapter calls the Top News endpoint once per run, flattens clustered headlines into `source_document` rows, and is designed for a 30-minute polling cadence within a 50-requests-per-day budget.

## Testing

```bash
pytest tests/ -v
ruff check app/ tests/ scripts/
```

See [docs/architecture.md](docs/architecture.md) for full architecture overview.
