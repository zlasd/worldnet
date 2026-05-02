# worldnet

Personal stock news/announcement event radar — fetches, classifies, and prioritizes market events for tracked instruments.

## Quick Start

```bash
pip install -e ".[dev]"
python scripts/init_db.py      # create DB tables
python scripts/seed_data.py    # seed sample instruments & watchlist
python scripts/run_pipeline.py # run ingestion pipeline
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

1. **Ingest** — fetch raw documents from adapters (RSS, official announcements)
2. **Dedupe** — detect duplicate content by hash
3. **Entity Match** — link documents to instruments (ticker / name / alias)
4. **Normalize** — classify event type, sentiment, severity
5. **Prioritize** — P1/P2/P3 based on severity + watchlist membership
6. **Notification** — log notification records

## Testing

```bash
pytest tests/ -v
ruff check app/ tests/ scripts/
```

See [docs/architecture.md](docs/architecture.md) for full architecture overview.
