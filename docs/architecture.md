# Architecture Overview

[中文文档 / Chinese docs](architecture_cn.md)

## 1. System overview

WorldNet is an event radar for investment research. It:

1. Fetches raw documents from announcement and news sources
2. Deduplicates and entity-matches them against instruments
3. Normalizes them into structured events
4. Prioritizes them based on watchlists and severity

## 2. Pipeline flow

```text
Sources (official announcements / RSS / RSSHub / World News API)
        │
        ▼
[1] Ingest          Persist raw data into source_document
        │
        ▼
[2] Dedupe          Detect duplicates via content_hash / canonical_hash
        │
        ▼
[3] Entity Match    Link documents to instruments
        │
        ▼
[4] Normalize       Produce normalized_event records
        │
        ▼
[5] Prioritize      Assign priority from watchlists and severity
        │
        ▼
[6] Notification    Write notification_log entries
```

## 3. Core data models

| Model | Purpose |
| --- | --- |
| `Instrument` | Base information for an equity or tracked instrument |
| `Watchlist` / `WatchlistItem` | User-defined watchlists |
| `SourceDocument` | Raw ingested documents |
| `DocumentEntityMatch` | Links between documents and instruments |
| `NormalizedEvent` | Structured normalized events |
| `EventImpact` | Per-instrument impact assessment |
| `NotificationLog` | Outbound notification records |

## 4. Source design

Current sources fall into two groups:

- **Fixed sources**
  - `official_announcement`
  - `rsshub_cls_telegraph`
  - `rsshub_cls_depth`
  - `worldnewsapi_top_news`

- **Parameterized sources**
  - `rsshub_sse_disclosure`
  - `rsshub_szse_listed_notice`

Parameterized sources build their RSSHub route from `source_config`, which lets them support both:

- Manual replay for a specific ticker
- Scheduler-driven expansion from watchlist instruments

## 5. Scheduler design

The scheduler has been upgraded from source-based polling to task-driven scheduling.

### 5.1 Task loading

At startup, the scheduler reads:

- `config/tasks/default`
- `config/tasks/custom`

YAML files from both directories are merged by `task_id`, so the custom directory can:

- Add tasks
- Override task fields
- Disable built-in tasks

### 5.2 Task structure

Each task definition contains:

- `task_id`
- `enabled`
- `source`
- `interval_minutes` or `cron`
- `selector`
- `source_config`

### 5.3 Dynamic expansion

If a task includes a selector such as:

- `watchlist_only: true`
- `market: CN`
- `exchange: SSE`

the scheduler queries `watchlist` and `instrument`, then expands the task into concrete jobs.

For example:

- `rsshub-sse-watchlist-disclosure`

may expand into:

- `rsshub-sse-watchlist-disclosure:<instrument_id_1>`
- `rsshub-sse-watchlist-disclosure:<instrument_id_2>`

## 6. A-share announcement monitoring

### 6.1 SSE

RSSHub route:

- `/sse/disclosure/:query?`

WorldNet constructs per-instrument routes with `productId=<ticker>`.

### 6.2 SZSE

RSSHub route:

- `/szse/disclosure/listed/notice/:query?`

WorldNet constructs per-instrument routes with `stock=<ticker>`.

### 6.3 Why expand per instrument

Instead of fetching the whole exchange feed and filtering afterward, WorldNet expands tasks from watchlist instruments directly. This gives:

- More precise requests
- Less noise
- Better downstream entity matching
- A cleaner extension path for future markets or task templates

## 7. Entity matching note

Exchange announcements do not always include complete security identifiers in the body, so matching now uses a combination of:

- `title`
- `author`
- `raw_text`

The parameterized RSSHub adapters also inject instrument hint text into the raw content to improve A-share matching accuracy.

## 8. Deployment layout

Docker deployment uses four services:

- `app`
- `scheduler`
- `rsshub`
- `postgres`

Key relationships:

- `app` and `scheduler` share the same image
- `scheduler` reuses the `run_pipeline()` entrypoint
- `rsshub` provides a unified upstream route layer
- `postgres` stores production data

## 9. Design tradeoffs

The implementation intentionally stays lightweight:

- No external distributed scheduler
- Cron support is limited to common 5-field expressions
- Task state is not persisted in the database
- New code and config are loaded through deploy-time restart

This keeps the project:

- Maintainable
- Easy to deploy
- Easy to extend with additional sources
