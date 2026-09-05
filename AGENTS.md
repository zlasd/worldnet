# WorldNet：Agent 工作指南

本文件适用于整个仓库，帮助快速定位实现与约束。具体行为以当前代码、配置和测试为准；不要把设计建议当成已实现功能。

## 目标与工作方式

WorldNet 是面向个人投资研究的事件雷达：采集公告与新闻，关联关注标的，生成结构化事件和日报。当前还包含股指期货研究模块、海外采集和海外到境内的单向同步。

- 保持现有 Python 单体、SQLAlchemy、YAML 配置设计；优先扩展已有模块，不为小功能引入新的服务或调度框架。
- 开始先运行 `git status --short`，保留用户已有改动；按下方索引只读相关代码与测试，无需每次通读全仓库。
- 先查实际调用链。部分架构文档早于实现，不能仅凭文件名推断功能已经接通。
- 变更应包含必要的回归验证与配置说明。保持本指南简短，不记录会话流水账、固定测试数量或提交哈希。

## 技术栈与验证

Python ≥3.11；FastAPI / Pydantic v2；SQLAlchemy 2 / Alembic；生产 PostgreSQL，开发默认 SQLite；pytest / Ruff。依赖见 `pyproject.toml` 和 `uv.lock`。

从仓库根目录执行，优先复用已有 `.venv`：

```bash
# 仅在缺少环境或需要同步依赖时执行
uv sync --frozen --extra dev

# 常用验证
.venv/bin/pytest -q
.venv/bin/ruff check .
git diff --check

# 修改部署或同步 Shell 脚本时
bash -n scripts/deploy.sh scripts/push_sync_batch.sh scripts/import_sync_inbox.sh
```

- 开发时先跑相关测试；涉及数据库、调度、日报或同步的变更，完成后跑全套测试。
- `tests/conftest.py` 的 `session` 使用内存 SQLite；同步可靠性测试另建启用外键的独立目标数据库。
- 外部 HTTP、LLM、通知调用使用 fake / monkeypatch。不要把启动调度器、运行部署脚本或发送通知当作测试。
- Ruff 配置以项目为准：行宽 100，启用 E/F/I，忽略 E501；避免无关文件的批量格式化。

## 代码导航

| 工作内容 | 首先查看 | 对应测试 |
| --- | --- | --- |
| 新增源、RSS/Atom、公告路由 | `app/adapters/base.py`、`factory.py`、具体 adapter | `test_rsshub_route_adapter.py`、`test_worldnewsapi_adapter.py` |
| 入库、去重、实体匹配、事件归一化 | `app/pipelines/runner.py`、`ingest.py`、`dedupe.py`、`entity_match.py`、`normalize_event.py`；`app/rules/` | `test_pipeline_runner.py`、`test_dedupe.py`、`test_entity_match.py`、`test_normalize_event.py` |
| YAML 任务与调度 | `app/tasks/task_config.py`、`scheduler.py`、`pipeline_task.py` | `test_task_config.py`、`test_scheduler.py`、`test_overseas_profile.py` |
| 日报筛选、生成、展示 | `app/digests/config.py`、`runner.py`、`selection.py`、`llm.py`、`types.py`、`image.py` | `test_digest_selection.py`、`test_digest_runner.py`、`test_digest_llm.py`、`test_digest_image.py` |
| 通知出口与发送 | `app/digests/dispatcher.py`、`app/notifications/`；宿主机桥接见 `scripts/worldnet-hermes-*` | `test_notification_*.py`、`test_hermes_bridge.py` |
| 海外同步 | `app/sync/transfer.py`、`client.py`、`receiver.py`、`importer.py`、`receipts.py`；`scripts/*sync*` | `test_sync_transfer.py`、`test_sync_receiver.py`、`test_sync_reliability.py` |
| 关注列表、API、数据库 | `app/watchlists/`、`app/api/`、`app/services/`、`app/models/`、`app/schemas/`、`migrations/versions/` | `test_watchlist_*.py`、`test_api_auth.py`、`test_alembic_migration.py` |
| 股指期货行情、贴水、估值、模拟策略 | `app/index_futures/official.py`、`service.py`、`metrics.py`、`paper.py`、`commentary.py`、`report.py` | `test_index_futures_*.py` |

表内测试文件均位于 `tests/`。运行入口主要为 `scripts/run_pipeline.py`、`scripts/run_scheduler.py` 和 `app.api.main:app`。

## 主流程与配置

采集流程：`BaseAdapter → ingest → dedupe → entity_match → normalize_events`，由 `run_full_pipeline()` 串联，`app/tasks/pipeline_task.py` 管理事务。当前该流程返回 `notifications_prepared=0`，不要假定每次采集都会即时发送通知。日报通过独立任务筛选并发送。

- `app/core/config.py` 的 Settings 在导入时读取 `.env`；数据库引擎也在模块导入时初始化。测试应使用隔离 session，不操作默认数据库。
- 任务从 `config/tasks/default/` 与可配置的 custom 目录按 `task_id` 合并；嵌套字典递归覆盖，列表整体替换。`enabled: false` 禁用任务；`cron` 与 `interval_minutes` 必须且只能设置一个。
- 调度器每轮重新读取任务配置并按 watchlist 展开 job；运行状态保存在内存，重启不保留任务进度。
- 海外配置位于 `config/tasks/overseas/oci.yaml`，通过 `SCHEDULER_TASKS_CUSTOM_DIR=config/tasks/overseas` 加载。仅设置 `WORLDNET_OVERSEAS_PROFILE=true` 不会自动切换任务目录。
- 通知和关注列表配置分别位于 `config/notifications/`、`config/watchlists/`；本地 custom 配置通常被 Git 忽略，不代表所有机器都具有相同配置。

## 必须保持的行为

### 日报

- 先独立执行主题/排除词过滤和重要性排序，再截取 `max_candidates`，最后调用 LLM 或规则降级。主题约束不能只放在 LLM 提示词里。
- 排序优先级：P1/P2/P3、有效关注标的关联、严重程度、时效。关注关联包含主标的和相关标的，排除停用的列表与关注项。
- 来源、URL、发布时间、规则优先级和入选依据来自数据库候选记录，不信任 LLM 伪造的溯源字段；拒绝重复 event ID。渲染 HTML 时转义内容，仅输出安全 HTTP(S) 原文链接。
- 没有通知出口时仍保存 `DigestLog` 和 `DigestItem`，同步依赖这些关联。境内日报窗口只读取 `source_instance IS NULL` 的本地日报。
- 时间窗口为左闭右开；数据库日期通常以 UTC naive 存储，边界显式转换；调度时区默认 `Asia/Shanghai`，不要混用宿主机本地时间。

### 同步

- `receiver` 仅鉴权、校验和写 inbox，不持有数据库凭据；导入由独立进程执行。保持 HTTPS + SPKI pin + HMAC；`curl --insecure` 只可与强制公钥 pin 同时使用。
- 上传成功不等于导入成功：只有数据库事务提交后才能写签名 `imported` 回执；发送端校验来源、批次 ID、内容签名后才推进游标。
- 文档/事件与日报使用独立游标；日报按 `updated_at` 选取，并携带完整条目、事件和文档依赖，包含空日报。
- outbox 重试使用原批次，写文件与游标采用原子替换；失败不得删除待处理批次或推进游标。手动补传不推进自动游标，旧回执不能使游标倒退。
- 保留主键/内容 hash 幂等、旧批次兼容、较新日报版本保护及 `digest_items_complete` 完整快照语义；旧版部分条目不能覆盖新版完整快照。
- 境内拥有 instrument 主数据；同步不复制海外 instrument，只接收能够关联到境内既有标的的实体匹配。不要直接跨实例导入未知标的外键。
- 修改同步时至少覆盖：独立目标数据库、重复批次、延迟日报、事务回滚、回执写入失败、错误回执、旧版批次及重放。

## 已知边界与部署注意

- `official_announcement` **仍是固定示例数据源**，并非真实官方抓取；真实沪深公告走参数化 RSSHub adapter。`all` 不包含需要必填参数的源。
- 主题筛选是关键词与源标签规则，不是语义分类器；跨源语义事件聚合、来源健康告警、行业影响传播尚未实现。
- 数据模型变化需同步 ORM、必要的 schema/API 和 Alembic 迁移；对已有库使用 `alembic upgrade head`，不能用 `create_all()` 代替升级。
- Compose 默认包含 app、scheduler、RSSHub、PostgreSQL；同步接收端由 `sync-receiver` profile 启用。`scripts/deploy.sh` 会构建镜像、执行迁移并启动服务，具有真实副作用。
- 同步升级顺序：先境内、后海外；两端迁移并重建镜像。默认上传压缩上限 16 MiB、解压上限 64 MiB，目前不自动分片；长时间历史补传使用较小区间。
- `.env`、私钥、数据库、`deploy/` 和私有 custom 配置不应提交；也不要输出凭据值。Git 忽略不等于 Docker 忽略，改构建过程时同时检查 `.dockerignore` 与 `COPY`。
- 文档中的服务器地址与账号使用示例值。推送、部署、迁移生产库或发送通知按用户已授权范围执行；本地测试通过不代表线上已部署或验证。

## 按需阅读

- [日报筛选、同步协议、补传与升级](docs/digests_and_sync_cn.md)：涉及日报或同步时优先读。
- [部署与配置](docs/deployment_cn.md)：环境变量、通知出口、容器与服务器操作。
- [架构说明](docs/architecture_cn.md)：基础数据模型与设计背景；可能落后于当前调用链。
