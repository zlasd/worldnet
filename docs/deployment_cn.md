# 部署与配置说明

本文档集中说明 WorldNet 的运行配置、任务调度、Docker 部署和升级方式。

## 1. 数据库

项目同时支持两种数据库后端：

- **开发环境**：默认使用 SQLite
  - `DATABASE_URL=sqlite:///./worldnet.db`
- **生产环境**：推荐使用 PostgreSQL
  - `DATABASE_URL=postgresql+psycopg://worldnet:worldnet@postgres:5432/worldnet`

初始化或升级数据库 schema：

```bash
alembic upgrade head
```

`python scripts/init_db.py` 仍可用于本地快速初始化；部署环境建议使用 Alembic，后续表结构变更才能被持续追踪。

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
| `kind` | 任务类型；默认 `pipeline`，日报任务使用 `digest` |
| `digest_type` | 日报类型；当前支持 `important_daily` |
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

### 2.5 OCI 海外采集配置

仓库提供了独立的海外采集 profile：`config/tasks/overseas/oci.yaml`。OCI 实例使用该目录时，会禁用财联社、沪深交易所公告和 World News API 任务，只调度 Bloomberg、Wall Street Journal、BBC 的公开 RSS 标题/摘要，并将日报范围限制为经济与政治。该 profile 不绕过付费墙，也不抓取全文。

OCI 的 `.env` 至少应包含：

```bash
WORLDNET_OVERSEAS_PROFILE=true
SCHEDULER_TASKS_CUSTOM_DIR=config/tasks/overseas
NOTIFICATION_CONFIG_CUSTOM_DIR=config/notifications/overseas
WORLDNET_BIND_ADDRESS=127.0.0.1
RSSHUB_BIND_ADDRESS=127.0.0.1
```

其中 `config/notifications/overseas` 可以为空目录，表示日报只写入数据库，不配置外部通知出口。`WORLDNET_OVERSEAS_PROFILE=true` 时，`scripts/deploy.sh` 会跳过境内股指期货回填和境内 watchlist 同步。

## 3. 已内置的默认任务

仓库默认提供这些任务：

- 财联社电报：`rsshub_cls_telegraph`
- 财联社深度：`rsshub_cls_depth`
- watchlist 中上交所 A 股公告：`rsshub_sse_disclosure`
- watchlist 中深交所 A 股公告：`rsshub_szse_listed_notice`
- World News API Top News：默认关闭
- WorldNet 重要事项日报：`important_daily`，默认关闭

其中上交所和深交所公告任务会在运行时自动筛选：

- watchlist 中的标的
- `market=CN`
- `exchange=SSE` 或 `exchange=SZSE`

并按股票代码展开成实际抓取任务。

### 3.1 重要事项日报任务

日报任务使用 `kind: digest`，不会运行 source adapter。默认任务 `daily-important-digest` 关闭，可在 `config/tasks/custom` 中启用：

```yaml
tasks:
  - task_id: daily-important-digest
    enabled: true
    cron: "30 7 * * *"
    source_config:
      selection:
        max_candidates: 50
        max_items: 10
      llm:
        user_prompt: |
          优先选择对持仓、监管、财报、重大风险有直接影响的信息。
```

LLM 使用 OpenAI 兼容 `/chat/completions`，通过 BYOK 配置：

```bash
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=your-api-key
LLM_MODEL=gpt-4.1-mini
LLM_TIMEOUT_SECONDS=60
```

`llm.user_prompt` 只作为筛选偏好和写作风格注入；固定 JSON 输出 schema 和校验规则不能被任务覆盖。LLM 不可用或输出不合格时，系统会发送规则降级日报。

### 3.2 Watchlist 维护

推荐把 watchlist 作为 YAML 配置维护，目录为：

- `config/watchlists/default`
- `config/watchlists/custom`

手工添加股票时可以只输入代码，脚本会自动识别市场并尝试通过公开接口补全公司名等字段：

```bash
python scripts/watchlist_add.py A股观察 600519 --priority high --holding
python scripts/watchlist_add.py 海外观察 0700.HK --priority medium
python scripts/watchlist_add.py 海外观察 AAPL --priority high --exchange NASDAQ
```

脚本只更新 YAML，不直接写数据库。同步入库：

```bash
python scripts/sync_watchlists.py
```

Docker 部署中可执行：

```bash
docker compose run --rm app python scripts/watchlist_add.py A股观察 600519 --priority high --holding
docker compose run --rm app python scripts/sync_watchlists.py
```

如果要预览变更：

```bash
python scripts/watchlist_add.py A股观察 600519 --dry-run
python scripts/sync_watchlists.py --dry-run
```

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

## 5. 通知出口配置

WorldNet 的通知出口通过 YAML + `.env` 共同配置：

- YAML：定义出口实例、是否启用、出口类型、非敏感参数
- `.env`：保存命令、目标、token、超时等部署环境相关参数

配置目录：

```bash
NOTIFICATION_CONFIG_DEFAULT_DIR=config/notifications/default
NOTIFICATION_CONFIG_CUSTOM_DIR=config/notifications/custom
```

`config/notifications/default` 提供内置出口模板；`config/notifications/custom` 默认不纳入版本管理，适合服务器本地启用或覆盖出口。

示例：启用 QQ Agent Mail 和 Hermes 微信两个出口：

```yaml
outlets:
  - outlet_id: qq_agent_mail
    type: qq_agent_mail
    enabled: true
    channel: email

  - outlet_id: hermes_weixin
    type: hermes_http
    enabled: true
    channel: weixin
```

通知会对所有启用出口执行 fan-out：同一个事件会按 `event_id + outlet_id` 去重，每个出口独立记录发送成功或失败。

### 5.1 QQ Agent 邮箱出口

WorldNet 可以通过 QQ Agent 原生邮箱发送通知。Docker 镜像会内置 `agently-cli`，并通过 `agently_credentials` volume 持久化 CLI 凭据。容器内会将 `HOME` 设置为 `/var/lib/worldnet`，该目录由 volume 挂载，避免重建镜像后丢失 OAuth 凭据。

为适配中国大陆服务器网络，Dockerfile 默认使用腾讯云 Debian/PyPI 镜像和 npmmirror npm 镜像；服务器上的 Docker daemon 建议配置境内 registry mirror。

本地非 Docker 运行时，首次使用前需要安装并授权 `agently-cli`：

```bash
npm install -g @tencent-qqmail/agently-cli
agently-cli auth login
agently-cli +me
```

授权成功后，在 `.env` 中配置邮件出口：

```bash
QQ_AGENT_MAIL_TO=receiver@example.com
QQ_AGENT_MAIL_CLI_COMMAND=agently-cli
QQ_AGENT_MAIL_TIMEOUT_SECONDS=30
QQ_AGENT_MAIL_AUTHORIZED_EMAIL=your-authorized@qq.com
```

如果运行环境没有全局安装 CLI，也可以把 `QQ_AGENT_MAIL_CLI_COMMAND` 设置为：

```bash
QQ_AGENT_MAIL_CLI_COMMAND=npx -y @tencent-qqmail/agently-cli
```

发送时会自动调用 `agently-cli message +send` 并完成确认 token 流程。OAuth token 由 `agently-cli` 自身保存，`.env` 只保存 WorldNet 侧的出口配置和已授权邮箱标识。

### 5.2 远程 Docker 授权

远程服务器不需要图形界面。先构建镜像：

```bash
docker compose build app scheduler
```

如果需要升级镜像内的 `agently-cli` 版本，可以显式传入版本号：

```bash
docker compose build --build-arg AGENTLY_CLI_VERSION=1.0.6 app scheduler
```

然后在服务器 SSH 终端里执行授权命令：

```bash
docker compose run --rm scheduler agently-cli auth login
```

命令会输出一个 `https://agent.qq.com/page/oauth?...` 授权链接。复制这个链接到本地电脑或手机浏览器打开并完成授权；授权完成后，服务器终端会显示认证成功。

验证授权：

```bash
docker compose run --rm scheduler agently-cli auth status
docker compose run --rm scheduler agently-cli +me
```

确认授权邮箱后，把 `.env` 中的 `QQ_AGENT_MAIL_AUTHORIZED_EMAIL` 设置为 `+me` 返回的邮箱，并按需要设置 `QQ_AGENT_MAIL_TO`。凭据保存在 `agently_credentials` volume 中，重建 app/scheduler 镜像不会丢失；如果删除该 volume，需要重新执行 OAuth。

### 5.3 Hermes 媒体桥与 QQ Bot 出口

WorldNet 通过宿主机 HTTP bridge 发送消息。QQ Bot 出口由 bridge 直接调用 QQ 官方
REST API；微信等其他 Hermes 通道继续调用 `hermes send`。容器不挂载 `~/.hermes`。

```bash
sudo install -m 0755 scripts/worldnet-hermes-bridge.py /usr/local/bin/worldnet-hermes-bridge
sudo install -m 0644 scripts/worldnet-hermes-bridge.service /etc/systemd/system/worldnet-hermes-bridge.service
sudo systemctl daemon-reload
sudo systemctl enable --now worldnet-hermes-bridge
```

日报默认渲染为单张 JPEG，并通过宿主机共享目录
`/home/ubuntu/worldnet-data/notification-media` 交给 bridge 上传。桥接服务只允许读取该目录下、
不超过 8 MiB 的 JPEG/PNG/WebP 文件，并拒绝路径穿越。`scripts/deploy.sh` 会幂等创建目录；
若自定义 `NOTIFICATION_MEDIA_HOST_DIRECTORY`，需同步修改桥接服务的
`HERMES_BRIDGE_MEDIA_DIRECTORY`。

`.env` 示例：

```bash
HERMES_BRIDGE_URL=http://host.docker.internal:15307/send
HERMES_WEIXIN_TARGET=
HERMES_QQBOT_TARGET=qqbot:c2c:your-user-openid
QQ_APP_ID=your-qq-bot-app-id
QQ_CLIENT_SECRET=your-qq-bot-client-secret
HERMES_SEND_TIMEOUT_SECONDS=30
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=your-api-key
LLM_MODEL=gpt-4.1-mini
LLM_TIMEOUT_SECONDS=60
```

QQ 目标支持 `qqbot:c2c:<OPENID>` 和 `qqbot:group:<GROUP_OPENID>`。先在
[QQ 开放平台](https://q.qq.com/)创建机器人并与其互动一次以取得对应 OpenID，然后在
`config/notifications/custom/outlets.yaml` 中启用 `hermes_qqbot`、禁用
`hermes_weixin`。bridge 的 systemd 单元通过 `EnvironmentFile` 读取同一份
`/home/ubuntu/worldnet/.env`，无需再维护第二份凭据。

对于非 QQ 的 Hermes 通道，bridge 进程内部会调用：

```bash
/home/ubuntu/.local/bin/hermes send --to "<target>" --json
```

默认 systemd 示例监听 `0.0.0.0:15307`，但应用层只允许 `127.0.0.0/8` 和 `172.16.0.0/12` 来源。Docker Compose 已配置 `host.docker.internal:host-gateway`，容器会通过 Docker bridge 访问宿主机。生产环境可以进一步收紧：

```bash
sudo systemctl edit worldnet-hermes-bridge
```

```ini
[Service]
Environment=HERMES_BRIDGE_ALLOWED_CIDRS=172.18.0.0/16
```

如果 WorldNet 不运行在 Docker 内，也可以继续使用命令桥兼容模式：

```bash
sudo install -m 0755 scripts/worldnet-hermes-send.sh /usr/local/bin/worldnet-hermes-send
```

并在 YAML 中启用 `type: hermes_send` 的 outlet。

## 6. Docker 部署

仓库已经提供：

- `Dockerfile`
- `docker-compose.yml`
- `scripts/deploy.sh`

### 6.1 启动方式

```bash
docker compose up -d postgres rsshub
docker compose run --rm app python scripts/init_db.py
docker compose up -d app scheduler
```

更推荐直接使用升级脚本：

```bash
./scripts/deploy.sh
```

如果通过 `git archive` 分发源码，解压时使用 `tar --same-permissions -xzf` 保留
仓库的文件模式，避免备份脚本的 `umask 077` 把源码变成仅 root 可读。同步接收容器
以非 root 用户运行；构建后应以其实际 UID/GID 验证 `import app.sync.receiver`，
再检查接收容器持续运行及真实同步回执。API `/health` 正常不能证明接收端正常。
备份目录、`.env` 和私钥仍保持原有的严格权限，不对它们批量放宽权限。

### 6.2 `docker-compose.yml` 包含的服务

- `app`：FastAPI API 服务
- `scheduler`：调度器
- `rsshub`：RSSHub 服务
- `postgres`：PostgreSQL

### 6.3 海外到境内的单向同步

新增的独立日报游标、签名导入回执、补传和升级步骤见 [日报筛选与可靠同步](digests_and_sync_cn.md)。

海外 OCI 通过专用 HTTPS 接收端把签名的 gzip JSON 批次上传到境内 VPS；境内定时导入。批次使用 `WORLDNET_SYNC_SECRET` 做 HMAC-SHA256 校验，导入按主键和内容 hash 幂等去重。同步只传输文档、事件和日报记录，不传输海外实例的 instrument 主数据；境内只有已存在的 instrument 才会接收对应实体匹配。

境内 `.env` 启用接收端，OCI `.env` 配置接收 URL 和公钥 pin（示例值不可直接使用）：

```bash
# 境内
WORLDNET_SYNC_RECEIVER_ENABLED=true
WORLDNET_SYNC_RECEIVER_PORT=15308
WORLDNET_SYNC_TLS_HOST_DIRECTORY=/home/ubuntu/worldnet-data/sync-tls

# OCI
WORLDNET_SYNC_URL=https://境内域名或IP:15308/upload
WORLDNET_SYNC_TLS_PIN=sha256//服务端公钥SPKI的base64摘要
```

若使用自签名证书，客户端仍会通过 `WORLDNET_SYNC_TLS_PIN` 校验服务端公钥；不要把 `WORLDNET_SYNC_SECRET` 写入 URL 或提交到仓库。

境内云防火墙只需放行一条最小规则：`TCP 15308`，来源限制为实际 OCI 公网 IP 对应的 `/32` 地址（例如文档示例地址 `192.0.2.10/32`，部署时必须替换）。不要将该端口开放给 `0.0.0.0/0`；OCI 端不需要新增入站规则。

默认定时器为：OCI HTTPS 上传每 10 分钟，境内导入每 5 分钟。接收端使用 TLS 证书，并要求 `Authorization: Bearer` 和来源实例标识；客户端通过 `WORLDNET_SYNC_TLS_PIN` 固定服务端公钥，避免依赖公共 CA。两端的同步目录通过 `WORLDNET_SYNC_HOST_DIRECTORY` 挂载到容器内的 `WORLDNET_SYNC_CONTAINER_DIRECTORY`，密钥、接收地址和证书 pin 只放在两端 `.env`，不提交到仓库。安装模板位于 `deploy/worldnet-sync/`，手动运行入口分别是：

```bash
sudo systemctl start worldnet-sync-push.service     # OCI，HTTPS 上传
sudo systemctl start worldnet-sync-import.service   # 境内
```

推送方向是 OCI → 境内；境内仅新增一个 HTTPS 上传端口（默认 `15308`），不再创建或保留同步专用 SSH/SFTP 登录账号，也不要求境内端反向访问 OCI。

## 7. 升级流程

推荐的服务器升级流程：

1. 更新仓库到目标分支或提交
2. 维护 `.env`、`config/tasks/custom` 等本地配置
3. 执行 `./scripts/deploy.sh`

升级脚本会：

1. 重建 `app` / `scheduler` 镜像
2. 启动 `postgres` 和 `rsshub`
3. 等待 PostgreSQL 就绪
4. 执行 Alembic 数据库迁移
5. 幂等回填至少 252 个共同交易日的股指期货期现数据，并推进模拟组合
6. 同步 watchlist
7. 启动 `app` 和 `scheduler`

股指期货回填从中金所月度 ZIP、中金所在市合约 XML 和中证指数 JSON 获取官方免费数据。
中证指数 JSON 的 `peg` 字段按官网历史行情定义作为滚动市盈率（PE）保存；日报默认用最近
252 个共同交易日计算 PE 历史分位，分位样本不足时会显示为不可用。可在日报任务的
`market_sections.index_futures_basis.pe_history_days` 调整回看长度（同时受可用官方历史数据限制）。
该步骤失败时只输出告警，不阻止服务启动；日报会使用数据库中的最近缓存并标注历史不足。
如需手工强制完整重抓，可执行：

```bash
docker compose run --rm app python scripts/backfill_index_futures.py --history-days 252 --force
```

日报中的 IF、IH、IC、IM 组合均为使用小数合约单位的标准化模拟研究组合，不连接真实账户，
也不会调用任何交易 API。LLM 只解释结构化指标，不参与选约、成交、成本或仓位更新；输出出现
指令性交易用语或缺少股息、现金利息、保证金收益、真实佣金和滑点提示时，会自动降级到确定性模板。

`postgres` 数据通过 volume 持久化，不会因为应用升级丢失。

## 8. 手动补跑

部署后仍然可以手动执行 pipeline，且会写入同一个数据库。

```bash
docker compose exec app python scripts/run_pipeline.py --source rsshub_cls_telegraph
docker compose exec app python scripts/run_pipeline.py --source rsshub_sse_disclosure --source-option product_id=600000 --source-option company_name=浦发银行
docker compose exec app python scripts/run_pipeline.py --source rsshub_szse_listed_notice --source-option stock=000001 --source-option company_name=平安银行
```

## 9. 生产环境常用变量示例

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
NOTIFICATION_CONFIG_DEFAULT_DIR=config/notifications/default
NOTIFICATION_CONFIG_CUSTOM_DIR=config/notifications/custom
QQ_AGENT_MAIL_TO=receiver@example.com
QQ_AGENT_MAIL_CLI_COMMAND=agently-cli
QQ_AGENT_MAIL_TIMEOUT_SECONDS=30
QQ_AGENT_MAIL_AUTHORIZED_EMAIL=your-authorized@qq.com
HERMES_BRIDGE_URL=http://host.docker.internal:15307/send
HERMES_WEIXIN_TARGET=
HERMES_QQBOT_TARGET=qqbot:c2c:your-user-openid
QQ_APP_ID=your-qq-bot-app-id
QQ_CLIENT_SECRET=your-qq-bot-client-secret
HERMES_SEND_TIMEOUT_SECONDS=30
```
