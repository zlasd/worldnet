# 架构说明

## 1. 系统概览

WorldNet 是一个面向投资研究的事件雷达。它负责：

1. 从公告或新闻源抓取原始文档
2. 做去重和实体匹配
3. 归一化成结构化事件
4. 按 watchlist 与严重程度生成优先级

## 2. 主流程

```text
数据源（官方公告 / RSS / RSSHub / World News API）
        │
        ▼
[1] Ingest          原始文档入库 source_document
        │
        ▼
[2] Dedupe          基于 content_hash / canonical_hash 去重
        │
        ▼
[3] Entity Match    将文档关联到 instrument
        │
        ▼
[4] Normalize       生成 normalized_event
        │
        ▼
[5] Prioritize      根据 watchlist 与严重程度生成优先级
        │
        ▼
[6] Notification    写入 notification_log
```

## 3. 关键数据模型

| 模型 | 作用 |
| --- | --- |
| `Instrument` | 股票或标的基础信息 |
| `Watchlist` / `WatchlistItem` | 关注列表与关注项 |
| `SourceDocument` | 原始抓取文档 |
| `DocumentEntityMatch` | 文档与标的的匹配关系 |
| `NormalizedEvent` | 归一化事件 |
| `EventImpact` | 事件对标的的影响 |
| `NotificationLog` | 通知记录 |

## 4. Source 设计

当前 source 分为两类：

- **固定 source**
  - `official_announcement`
  - `rsshub_cls_telegraph`
  - `rsshub_cls_depth`
  - `worldnewsapi_top_news`

- **参数化 source**
  - `rsshub_sse_disclosure`
  - `rsshub_szse_listed_notice`

参数化 source 的 route 在运行时按 `source_config` 构造，因此既可以：

- 手动指定股票代码补跑
- 也可以由调度器按 watchlist 动态展开

## 5. 调度器设计

调度器已经从“按 source 固定轮询”升级成“按任务配置驱动”。

### 5.1 任务来源

启动时会加载两个目录：

- `config/tasks/default`
- `config/tasks/custom`

两个目录中的 YAML 文件会按 `task_id` 合并，自定义目录可以：

- 新增任务
- 覆盖任务字段
- 禁用内置任务

### 5.2 任务结构

一个任务定义包含：

- `task_id`
- `enabled`
- `source`
- `interval_minutes` 或 `cron`
- `selector`
- `source_config`

### 5.3 动态展开

如果任务包含 selector，例如：

- `watchlist_only: true`
- `market: CN`
- `exchange: SSE`

调度器会先查询数据库中的 `watchlist` 与 `instrument`，再展开成实际 job。

例如：

- `rsshub-sse-watchlist-disclosure`

可能在运行时被展开为：

- `rsshub-sse-watchlist-disclosure:<instrument_id_1>`
- `rsshub-sse-watchlist-disclosure:<instrument_id_2>`

## 6. A 股公告监控设计

### 6.1 上交所

RSSHub route：

- `/sse/disclosure/:query?`

WorldNet 通过 `productId=<ticker>` 为单只股票构造 route。

### 6.2 深交所

RSSHub route：

- `/szse/disclosure/listed/notice/:query?`

WorldNet 通过 `stock=<ticker>` 为单只股票构造 route。

### 6.3 为什么按标的展开

不抓全量公告再过滤，而是直接按 watchlist 标的展开任务，优点是：

- 请求更精准
- 噪音更少
- 对下游实体匹配更友好
- 更容易继续扩展到不同市场或不同模板

## 7. 实体匹配补充

对于交易所公告，文档正文并不总是包含完整证券信息，所以当前匹配阶段会综合使用：

- `title`
- `author`
- `raw_text`

同时，参数化 RSSHub adapter 也会在原始文本中补充标的提示信息，提升 A 股公告命中率。

## 8. 部署结构

Docker 部署包含四个服务：

- `app`
- `scheduler`
- `rsshub`
- `postgres`

其中：

- `app` 和 `scheduler` 共用同一份应用镜像
- `scheduler` 复用 `run_pipeline()` 入口
- `rsshub` 负责统一承接外部 route
- `postgres` 保存生产数据

## 9. 设计取舍

当前实现刻意保持简单：

- 不引入额外分布式调度框架
- cron 只支持常见 5 段表达式
- 任务状态不持久化到数据库
- 依赖部署时重启进程加载最新代码和配置

这样可以先保证：

- 可维护
- 易部署
- 易于新增数据源
