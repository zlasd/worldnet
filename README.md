# WorldNet

[中文文档 / Chinese docs](README_cn.md)

WorldNet is a personal event radar for investment research. It ingests announcements and news, links them to instruments, normalizes them into structured events, and prioritizes them based on watchlists.

## Current capabilities

- Exchange announcements from official sources and RSSHub routes
- Watchlist-driven monitoring for A-share instruments on SSE and SZSE
- YAML-based task scheduler with `interval_minutes` or `cron`
- Docker-friendly deployment with a separate API service and scheduler

## Quick start

```bash
pip install -e ".[dev]"
python scripts/init_db.py
python scripts/seed_data.py
python scripts/run_pipeline.py
python scripts/list_events.py
uvicorn app.api.main:app --reload
```

## Common commands

```bash
# Run built-in sources
python scripts/run_pipeline.py --source rsshub_cls_telegraph
python scripts/run_pipeline.py --source rsshub_cls_depth

# Run parameterized exchange announcement sources
python scripts/run_pipeline.py --source rsshub_sse_disclosure --source-option product_id=600000 --source-option company_name="Shanghai Pudong Development Bank"
python scripts/run_pipeline.py --source rsshub_szse_listed_notice --source-option stock=000001 --source-option company_name="Ping An Bank"

# Start the scheduler
python scripts/run_scheduler.py
```

## Documentation

- [Deployment and configuration](docs/deployment.md)
- [Architecture overview](docs/architecture.md)
- [中文部署说明](docs/deployment_cn.md)
- [中文架构说明](docs/architecture_cn.md)
