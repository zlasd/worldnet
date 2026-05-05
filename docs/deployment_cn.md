# 部署与配置说明

本文档集中说明 WorldNet 的运行配置、任务调度、Docker 部署和升级方式。

## 1. 数据库

项目同时支持两种数据库后端：

- **开发环境**：默认使用 SQLite
  - `DATABASE_URL=sqlite:///./worldnet.db`
- **生产环境**：推荐使用 PostgreSQL
  - `DATABASE_URL=postgresql+psycopg://worldnet:worldnet@postgres:5432/worldnet`

初始化数据库：

```bash
python scripts/init_db.py
```

## 2. 任务调度配置

调度器会同时加载两个目录下的 YAML 任务文件：

- 内置任务目录：`config/tasks/default`
- 自定义任务目录：`config/tasks/custom`

其中 `config/tasks/custom` 默认带有 `.gitignore`，适合保存服务器本地自定义任务而不纳入版本管理。

默认通过以下环境变量控制：

```bash
SCHEDULER_ENABLED=true
SCHEDULER_TICK_SECONDS=5
SCHEDULER_TIMEZONE=Asia/Shanghai
SCHEDULER_TASKS_DEFAULT_DIR=config/tasks/default
SCHEDULER_TASKS_CUSTOM_DIR=config/tasks/custom
```

### 2.1 任务文件格式

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

字段说明：

| 字段 | 说明 |
| --- | --- |
| `task_id` | 任务唯一标识，用于覆盖或禁用内置任务 |
| `enabled` | 是否启用 |
| `source` | 运行的 source 名称 |
| `interval_minutes` | 固定分钟间隔调度 |
| `cron` | cron 表达式，和 `interval_minutes` 二选一 |
| `selector` | 动态展开条件，例如 watchlist、市场、交易所 |
| `source_config` | 传给 adapter 的额外参数 |

### 2.2 禁用内置任务

如果想禁用项目自带任务，不需要修改 `config/tasks/default`，只要在 `config/tasks/custom` 新增覆盖文件：

```yaml
tasks:
  - task_id: rsshub-cls-depth
    enabled: false
```

### 2.3 任务配置与旧 source 开关的关系

当前仓库仍保留部分旧的 source 级环境变量开关，例如：

- `RSSHUB_CLS_TELEGRAPH_ENABLED`
- `RSSHUB_CLS_DEPTH_ENABLED`
- `WORLDNEWSAPI_ENABLED`

这些开关主要影响：

- `python scripts/run_pipeline.py --source all`

而 **scheduler 的定时行为以 YAML 任务文件为准**。如果要启用、禁用或修改定时任务，优先修改 `config/tasks/default` / `config/tasks/custom`。

### 2.4 启用默认关闭的 World News API 任务

项目保留了 World News API 接入，但默认关闭。启用方式：

1. 配置 API key
2. 在 `config/tasks/custom` 中覆盖内置任务

示例：

```bash
WORLDNEWSAPI_ENABLED=true
WORLDNEWSAPI_API_KEY=your-api-key
```

```yaml
tasks:
  - task_id: worldnewsapi-top-news
    enabled: true
```

## 3. 已内置的默认任务

仓库默认提供这些任务：

- 财联社电报：`rsshub_cls_telegraph`
- 财联社深度：`rsshub_cls_depth`
- watchlist 中上交所 A 股公告：`rsshub_sse_disclosure`
- watchlist 中深交所 A 股公告：`rsshub_szse_listed_notice`
- World News API Top News：默认关闭

其中上交所和深交所公告任务会在运行时自动筛选：

- watchlist 中的标的
- `market=CN`
- `exchange=SSE` 或 `exchange=SZSE`

并按股票代码展开成实际抓取任务。

## 4. RSSHub 与访问控制

### 4.1 WorldNet API 访问控制

如果设置了 `API_ACCESS_KEY`，所有 WorldNet HTTP 接口都需要鉴权，支持两种方式：

- `X-API-Key: <key>`
- `?key=<key>`

### 4.2 RSSHub 访问控制

如果设置了 `RSSHUB_ACCESS_KEY`：

- RSSHub 容器会通过 `ACCESS_KEY` 开启访问保护
- WorldNet 会自动为 route 生成对应的 `code`
- 不需要把原始 access key 写进 feed URL

相关环境变量：

```bash
API_ACCESS_KEY=your-worldnet-api-key
RSSHUB_BASE_URL=http://rsshub:1200
RSSHUB_ACCESS_KEY=your-rsshub-access-key
RSSHUB_TIMEOUT_SECONDS=30
```

## 5. Docker 部署

仓库已经提供：

- `Dockerfile`
- `docker-compose.yml`
- `scripts/deploy.sh`

### 5.1 启动方式

```bash
docker compose up -d postgres rsshub
docker compose run --rm app python scripts/init_db.py
docker compose up -d app scheduler
```

更推荐直接使用升级脚本：

```bash
./scripts/deploy.sh
```

### 5.2 `docker-compose.yml` 包含的服务

- `app`：FastAPI API 服务
- `scheduler`：调度器
- `rsshub`：RSSHub 服务
- `postgres`：PostgreSQL

## 6. 升级流程

推荐的服务器升级流程：

1. 更新仓库到目标分支或提交
2. 维护 `.env`、`config/tasks/custom` 等本地配置
3. 执行 `./scripts/deploy.sh`

升级脚本会：

1. 重建 `app` / `scheduler` 镜像
2. 启动 `postgres` 和 `rsshub`
3. 等待 PostgreSQL 就绪
4. 运行 `python scripts/init_db.py`
5. 启动 `app` 和 `scheduler`

`postgres` 数据通过 volume 持久化，不会因为应用升级丢失。

## 7. 手动补跑

部署后仍然可以手动执行 pipeline，且会写入同一个数据库。

```bash
docker compose exec app python scripts/run_pipeline.py --source rsshub_cls_telegraph
docker compose exec app python scripts/run_pipeline.py --source rsshub_sse_disclosure --source-option product_id=600000 --source-option company_name=浦发银行
docker compose exec app python scripts/run_pipeline.py --source rsshub_szse_listed_notice --source-option stock=000001 --source-option company_name=平安银行
```

## 8. 生产环境常用变量示例

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
