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

## Database Backends

WorldNet is designed to support multiple database backends:

- **Development**: SQLite via the default `DATABASE_URL=sqlite:///./worldnet.db`
- **Production**: PostgreSQL via `DATABASE_URL=postgresql+psycopg://...`

The ORM models and `scripts/init_db.py` are shared across both environments.

## API Access Control

If `API_ACCESS_KEY` is configured, all exposed WorldNet HTTP endpoints require authentication.

Supported ways to provide the key:

- HTTP header: `X-API-Key: <your-key>`
- Query parameter: `?key=<your-key>`

Example:

```bash
curl -H "X-API-Key: your-key" http://localhost:8000/health
curl "http://localhost:8000/health?key=your-key"
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
export RSSHUB_ACCESS_KEY=your-rsshub-access-key
export RSSHUB_CLS_TELEGRAPH_ENABLED=true
export RSSHUB_CLS_TELEGRAPH_POLL_INTERVAL_MINUTES=5
export RSSHUB_CLS_DEPTH_ENABLED=true
export RSSHUB_CLS_DEPTH_POLL_INTERVAL_MINUTES=30
```

Available RSSHub CLS sources:

- `rsshub_cls_telegraph` -> `/cls/telegraph`
- `rsshub_cls_depth` -> `/cls/depth`

When `RSSHUB_ACCESS_KEY` is configured, WorldNet will automatically generate the RSSHub `code` query parameter for each route, so it can consume protected RSSHub feeds without exposing the raw key in feed URLs.

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

## Scheduler

WorldNet includes a lightweight scheduler entrypoint:

```bash
python scripts/run_scheduler.py
```

The scheduler reads per-source enable flags and poll intervals from configuration, and repeatedly calls the existing `run_pipeline()` logic. It is intended to run as a separate process from the API server.

## Docker Deployment

The repository now includes:

- `Dockerfile` for the WorldNet application image
- `docker-compose.yml` for `app`, `scheduler`, `rsshub`, and `postgres`
- `scripts/deploy.sh` for server-side upgrades

Typical server workflow:

1. Update the repository to the target branch or commit.
2. Configure environment variables in `.env` or the shell.
3. Run:

```bash
./scripts/deploy.sh
```

The deploy script rebuilds the app image, starts `postgres` and `rsshub`, waits for PostgreSQL, runs `python scripts/init_db.py`, and then starts `app` plus `scheduler`.

### Manual Pipeline Runs After Deployment

Deployment does **not** remove the ability to run pipelines manually. For example:

```bash
docker compose exec app python scripts/run_pipeline.py --source rsshub_cls_telegraph
docker compose run --rm app python scripts/run_pipeline.py --source worldnewsapi_top_news
```

As long as the deployed `DATABASE_URL` points to PostgreSQL, both manual runs and scheduled runs write to the same PostgreSQL database.

### Public Access Keys in Deployment

If you expose `app` and `rsshub` publicly, set both:

```bash
API_ACCESS_KEY=your-worldnet-api-key
RSSHUB_ACCESS_KEY=your-rsshub-access-key
```

- WorldNet validates `API_ACCESS_KEY` itself.
- RSSHub uses `ACCESS_KEY`.
- WorldNet uses `RSSHUB_ACCESS_KEY` to generate RSSHub route-specific access codes automatically.

### Key Production Environment Variables

```bash
DATABASE_URL=postgresql+psycopg://worldnet:worldnet@postgres:5432/worldnet
API_ACCESS_KEY=your-worldnet-api-key
RSSHUB_BASE_URL=http://rsshub:1200
RSSHUB_ACCESS_KEY=your-rsshub-access-key
RSSHUB_CLS_TELEGRAPH_ENABLED=true
RSSHUB_CLS_TELEGRAPH_POLL_INTERVAL_MINUTES=5
RSSHUB_CLS_DEPTH_ENABLED=true
RSSHUB_CLS_DEPTH_POLL_INTERVAL_MINUTES=30
WORLDNEWSAPI_ENABLED=false
WORLDNEWSAPI_API_KEY=
WORLDNEWSAPI_POLL_INTERVAL_MINUTES=30
SCHEDULER_ENABLED=true
SCHEDULER_TICK_SECONDS=5
```

## Testing

```bash
pytest tests/ -v
ruff check app/ tests/ scripts/
```

See [docs/architecture.md](docs/architecture.md) for full architecture overview.
