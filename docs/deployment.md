# Deployment and Configuration

[中文文档 / Chinese docs](deployment_cn.md)

This document describes runtime configuration, task scheduling, Docker deployment, and upgrade workflow for WorldNet.

## 1. Database

WorldNet supports two database backends:

- **Development**: SQLite
  - `DATABASE_URL=sqlite:///./worldnet.db`
- **Production**: PostgreSQL
  - `DATABASE_URL=postgresql+psycopg://worldnet:worldnet@postgres:5432/worldnet`

Initialize the schema with:

```bash
python scripts/init_db.py
```

## 2. Scheduler task configuration

The scheduler loads YAML task files from two directories:

- Built-in task directory: `config/tasks/default`
- Custom task directory: `config/tasks/custom`

`config/tasks/custom` is ignored by Git by default, so it can hold server-local overrides without polluting the repository history.

Environment variables:

```bash
SCHEDULER_ENABLED=true
SCHEDULER_TICK_SECONDS=5
SCHEDULER_TIMEZONE=Asia/Shanghai
SCHEDULER_TASKS_DEFAULT_DIR=config/tasks/default
SCHEDULER_TASKS_CUSTOM_DIR=config/tasks/custom
```

### 2.1 Task file format

```yaml
tasks:
  - task_id: rsshub-sse-watchlist-disclosure
    enabled: true
    source: rsshub_sse_disclosure
    interval_minutes: 5
    selector:
      watchlist_only: true
      market: CN
      exchange: SSE
```

| Field | Description |
| --- | --- |
| `task_id` | Stable task identifier used for overrides or disabling built-in tasks |
| `enabled` | Whether the task is active |
| `source` | Source name to run |
| `interval_minutes` | Fixed interval schedule |
| `cron` | Cron expression; mutually exclusive with `interval_minutes` |
| `selector` | Dynamic expansion filters such as watchlist, market, and exchange |
| `source_config` | Extra adapter parameters |

### 2.2 Disable built-in tasks

You do not need to edit `config/tasks/default`. Add an override file under `config/tasks/custom` instead:

```yaml
tasks:
  - task_id: rsshub-cls-depth
    enabled: false
```

### 2.3 Relationship to legacy source flags

The repository still keeps some older source-level environment flags such as:

- `RSSHUB_CLS_TELEGRAPH_ENABLED`
- `RSSHUB_CLS_DEPTH_ENABLED`
- `WORLDNEWSAPI_ENABLED`

Those flags mainly affect:

- `python scripts/run_pipeline.py --source all`

The **scheduler itself is driven by YAML task files**. To enable, disable, or modify scheduled jobs, update `config/tasks/default` or `config/tasks/custom`.

### 2.4 Re-enable the optional World News API task

World News API support remains in the codebase but is disabled by default. To enable it:

1. Configure the API key
2. Override the built-in task in `config/tasks/custom`

Example:

```bash
WORLDNEWSAPI_ENABLED=true
WORLDNEWSAPI_API_KEY=your-api-key
```

```yaml
tasks:
  - task_id: worldnewsapi-top-news
    enabled: true
```

## 3. Built-in tasks

The repository currently ships with these default tasks:

- CLS telegraph: `rsshub_cls_telegraph`
- CLS long-form coverage: `rsshub_cls_depth`
- Watchlist SSE A-share disclosures: `rsshub_sse_disclosure`
- Watchlist SZSE A-share notices: `rsshub_szse_listed_notice`
- World News API Top News: disabled by default

The SSE and SZSE announcement tasks automatically filter:

- Instruments present in watchlists
- `market=CN`
- `exchange=SSE` or `exchange=SZSE`

and then expand into per-instrument jobs.

## 4. RSSHub and access control

### 4.1 WorldNet API access control

If `API_ACCESS_KEY` is configured, all HTTP endpoints require authentication via:

- `X-API-Key: <key>`
- `?key=<key>`

### 4.2 RSSHub access control

If `RSSHUB_ACCESS_KEY` is configured:

- The RSSHub container enables `ACCESS_KEY`
- WorldNet generates route-specific `code` values automatically
- The raw RSSHub access key does not need to appear in feed URLs

Relevant environment variables:

```bash
API_ACCESS_KEY=your-worldnet-api-key
RSSHUB_BASE_URL=http://rsshub:1200
RSSHUB_ACCESS_KEY=your-rsshub-access-key
RSSHUB_TIMEOUT_SECONDS=30
```

## 5. Docker deployment

The repository includes:

- `Dockerfile`
- `docker-compose.yml`
- `scripts/deploy.sh`

### 5.1 Start commands

```bash
docker compose up -d postgres rsshub
docker compose run --rm app python scripts/init_db.py
docker compose up -d app scheduler
```

The preferred production entrypoint is:

```bash
./scripts/deploy.sh
```

### 5.2 Services in `docker-compose.yml`

- `app`: FastAPI service
- `scheduler`: task scheduler
- `rsshub`: RSSHub service
- `postgres`: PostgreSQL

## 6. Upgrade workflow

Recommended server workflow:

1. Update the repository to the target branch or commit
2. Preserve `.env`, `config/tasks/custom`, and other local overrides
3. Run `./scripts/deploy.sh`

The deploy script:

1. Rebuilds the `app` and `scheduler` images
2. Starts `postgres` and `rsshub`
3. Waits for PostgreSQL
4. Runs `python scripts/init_db.py`
5. Starts `app` and `scheduler`

PostgreSQL data stays in a Docker volume across upgrades.

## 7. Manual replay

Manual pipeline runs are still supported after deployment and write into the same database:

```bash
docker compose exec app python scripts/run_pipeline.py --source rsshub_cls_telegraph
docker compose exec app python scripts/run_pipeline.py --source rsshub_sse_disclosure --source-option product_id=600000 --source-option company_name="Shanghai Pudong Development Bank"
docker compose exec app python scripts/run_pipeline.py --source rsshub_szse_listed_notice --source-option stock=000001 --source-option company_name="Ping An Bank"
```

## 8. Example production environment

```bash
DATABASE_URL=postgresql+psycopg://worldnet:worldnet@postgres:5432/worldnet
API_ACCESS_KEY=your-worldnet-api-key
RSSHUB_BASE_URL=http://rsshub:1200
RSSHUB_ACCESS_KEY=your-rsshub-access-key
SCHEDULER_ENABLED=true
SCHEDULER_TICK_SECONDS=5
SCHEDULER_TIMEZONE=Asia/Shanghai
SCHEDULER_TASKS_DEFAULT_DIR=config/tasks/default
SCHEDULER_TASKS_CUSTOM_DIR=config/tasks/custom
WORLDNEWSAPI_ENABLED=false
WORLDNEWSAPI_API_KEY=
```
