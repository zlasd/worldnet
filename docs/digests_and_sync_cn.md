# 日报筛选、原文溯源与可靠同步

## 日报筛选

`source_config.selection` 支持以下字段，LLM 开启、关闭或失败降级时都会先执行：

```yaml
selection:
  max_candidates: 100
  max_items: 12
  priorities: [p1, p2, p3]
  include_watchlist_only: false
  allowed_topics: [economy, politics]
  excluded_keywords: [球赛, 影评, horoscope]
```

- `allowed_topics` 默认为空，不限制主题；当前支持 `economy`（经济）和 `politics`（政治）。海外 OCI profile 默认启用这两个主题。
- 主题判断使用标题、正文的中英文关键词及源配置的 `metadata.topic`。混合资讯源中，体育、娱乐、生活方式等已识别的离题标题会覆盖源分类，避免仅凭 RSS 栏目标签放行。它是可解释的规则筛选，不是语义分类器；漏判或误判可通过词表与 `excluded_keywords` 调整。
- `excluded_keywords` 匹配标题和正文，优先排除；英文使用词边界匹配，中文使用子串匹配。LLM 提示词只提供补充偏好，不能替代这里的过滤配置。
- 先在整个日报时间窗口内过滤、排序，再截取 `max_candidates`。排序顺序为 P1 → P2 → P3、关联有效关注标的、严重程度、发布时间（缺失时使用检测时间），同分按事件 ID 稳定排序。
- 关注关联包含主标的与相关标的；已停用的关注列表和关注项不参与匹配。LLM 可以筛选和组织摘要，但不能伪造链接、发布时间或规则优先级。

文字、HTML、微信文字与图片日报均显示来源、原文地址、发布时间和规则入选依据。没有发布时间或 URL 时省略对应字段；HTML 原文链接仅接受不含账号密码的 HTTP(S) URL。原文信息从数据库文档记录补入，不使用 LLM 返回的溯源字段。

## 宏观日历与提前七天提醒

`macro-calendar-reminders` 是独立的 `kind: digest` / `digest_type: macro_calendar`
任务，只采集并确定性生成预告，不独立推送，也不经过 LLM 新闻筛选。默认按调度器时区
每天 07:00、13:00、19:00 更新日历并检查提醒；默认调度时区为 Asia/Shanghai。
07:00 的预告合并进入后续 07:30 重要事项日报。

首批日历来源：

- 境内：[国家统计局年度日程](https://www.stats.gov.cn/xxgk/sjfb/fbrcb/)，覆盖物价、
  PMI、国民经济运行、生产、消费、投资等主要指标；抓取当年及已公布的次年日程。
- 海外：[BLS 年度日程](https://www.bls.gov/schedule/)、
  [BEA 日程](https://www.bea.gov/news/schedule)、
  [FOMC 日程](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm)。
  BLS 筛选就业、物价、JOLTS、就业成本和生产率；BEA 筛选全国 GDP、个人收入与支出、
  国际贸易。FOMC 按例会结束日期预告，仅收录页面明确列出的纪要发布日期。

此任务只负责日历，实际公布值由下节的 `macro-data-releases` 任务采集。LPR、社融、海关、Census、初请失业金等
日历尚未接入；临时降准降息、未确定日期的报告和官员讲话不能凭惯例生成确定日期。
不因某条记录从页面消失就推断取消。明示的延期、取消可以产生更正。

配置见 `config/tasks/default/macro-calendar.yaml`，覆盖示例：

```yaml
tasks:
  - task_id: macro-calendar-reminders
    source_config:
      providers: [nbs]
      lead_days: 7
      display_timezone: Asia/Shanghai
      max_stale_hours: 48
```

海外 profile 将 providers 整体替换为 `[bls, bea, fed]`，每日北京时间 06:40、12:40、18:40
刷新；境内在 07:00、13:00、19:00 刷新并处理本地与导入的提醒，给既有每十分钟上传、
每五分钟导入定时器留出传输时间。两端 `SCHEDULER_TIMEZONE` 均需设为 `Asia/Shanghai`。
未使用海外采集时，单实例可
配置四个来源。`providers: []` 跳过本地抓取，已同步提醒仍可进入日报。`enabled: false` 禁用任务。

- 具有时刻的项目按 `display_timezone` 中的发布日期提前七个日历日提醒，
  美国时间使用 America/New_York，自动处理夏令时；仅有日期的项目明确显示原始
  时区和“具体时间待公布”，不假造午夜或固定发布时刻。
- 首次确认或恢复运行时若距发布不足七天，发“临近发布补充提醒”；已过时的发布
  不补发。日期修改后生成更正，若新日期仍在七天外，到新的提醒窗口再发预告。
- `macro_calendar_entry` 持久化日程和已生成提醒版本。发送完成状态按事件及出口
  从本地 DigestLog/DigestItem 查询；成功的出口不重复发送，失败出口在下轮重试。
  与既有通知一致，外部发送成功但数据库事务最终失败时仍存在重复投递的窗口，
  不承诺外部渠道 exactly-once。
- 日历访问失败保留旧状态并返回 warnings；超过 `max_stale_hours` 未确认的缓存
  不生成新预告。正文显示实际的最后核验时间。解析为空或页面结构不识别按失败处理。
- 提醒保存为 `macro_release_reminder` 事件及原始文档，标记经济主题、官方来源和
  独立 P1 优先级，不需要关联持仓；普通日报仍受自己的主题和关注列表筛选配置约束。
  宏观预告随 `important_daily` 合并发送，保留原文数值与时间，不交给 LLM 改写，
  不占用普通新闻的 `max_candidates` / `max_items` 配额；主题、排除词、优先级和关注列表
  限制仍在合并前独立执行。
- 文档的 `published_at` 保持空值；计划发布日期写入提醒内容和 metadata，避免
  将未来日程伪装为已发布数据。普通日报只选择同一日程的最新有效预告或更正。
- 没有通知出口也保存 DigestLog/DigestItem。海外原始日程表不跨实例复制，提醒
  文档、事件和日报沿用已有签名同步；境内日报将导入提醒合并后发至本地出口。

现有实例启用前必须执行 `alembic upgrade head`，并更新两端应用代码/镜像。
境内先升级、海外后升级；按实际通知配置决定由哪一端发送，避免两端同时向同一
外部出口投递。离线测试使用 fake HTTP 和 fake notifier；部署后需复测官方日历
可达性、时区和通知出口。本地代码及测试通过不代表生产提醒已启用。

## 实际公布值、央行决定和修订

`macro-data-releases`（`kind: digest` / `digest_type: macro_data`）直接读取官方公布值，
不通过 LLM 猜测数值。中国端配置 `[nbs, pbc]`，美国端配置 `[bls, bea, fed]`。
美国每三小时整点采集，中国在对应小时的第 20 分钟采集并处理已导入数据，均按
`Asia/Shanghai` 调度，给现有上传和导入定时器留出传输时间。

| 来源 | 已解析的数据 | 获取方式 |
| --- | --- | --- |
| 国家统计局 | CPI/核心 CPI 同比与环比、PPI、三类 PMI、GDP、工业增加值、社零、固定资产投资 | [最新发布](https://www.stats.gov.cn/sj/zxfb/)的正式数据表及明示字段 |
| 人民银行 | M1/M2、社融存量和累计增量、人民币贷款余额；准备金率等政策公告正文 | [调查统计](https://www.pbc.gov.cn/diaochatongjisi/116219/index.html)和[新闻发布](https://www.pbc.gov.cn/goutongjiaoliu/113456/113469/index.html) |
| 全国银行间同业拆借中心 | 1 年期、5 年期以上 LPR | [中国货币网 LPR](https://www.chinamoney.com.cn/chinese/bklpr/)页面使用的公开 JSON 接口 |
| BLS | CPI/核心 CPI 指数、非农就业总人数、失业率、平均时薪、最终需求 PPI 指数、JOLTS 职位空缺 | [公开 API](https://www.bls.gov/developers/api_signature_v2.htm)，每批请求九个序列、当年和上一年 |
| BEA | 实际 GDP 环比折年率、PCE/核心 PCE 同比环比、个人收入和消费支出环比 | [官方 RSS](https://apps.bea.gov/rss/rss.xml)发现发布页，读取正文与表格 |
| 美联储 | FOMC 声明及联邦基金目标利率区间 | [货币政策 RSS](https://www.federalreserve.gov/feeds/press_monetary.xml)及声明正文 |

- 实际值使用 Decimal，以字符串返回 JSON；`status: unavailable` / `value: null`
  明示缺数。BLS 的 M13 年均值不混入月度序列；没有比较基期时不计算同比/环比。
- BLS 指数涨幅、非农人数差额如由系统计算，`basis` 明确写明计算方法，通知标为
  “计算值”。这类差额使用同一批次已修订数据，不冒充机构新闻稿直接公布的增量。
- 每条记录保留统计期、单位、季调口径、官方脚注、来源、发布时间（如有）和抓取时间。
  当月、年初累计、同比、环比、美国 GDP 环比折年率使用不同序列标识，不混用口径。
- BLS API 不提供这批观测的原始发布时间，保持 `published_at: null`；只有日期的
  页面另存 `published_date`，不编造午夜。BLS 官方说明 API 可能较新闻发布滞后，
  因此本功能不承诺发布瞬间可得：[API 限制](https://www.bls.gov/bls/api_features.htm)。
- 用现有 SourceDocument 的结构化 metadata 保存不可变快照，数值、缺数标记、脚注
  或估计版本改变时新增版本，保留旧值及 `previous_document_id`。不需要新增数据库表
  或同步协议；所有快照随既有文档同步，事件和 DigestItem 携带正常依赖。
- 首次初始化保存历史，但每组只把最新统计期作为“首次采集快照”通知，避免将历史
  数据伪装成刚发布的新闻。后续新值和修订生成独立 P1 事件；普通日报排除已被新版本
  替代的事件；实际值和预告一起合入普通日报，不受新闻 LLM 选取或新闻条数上限影响。
- 通知按本地出口及事件记录去重，失败出口下轮重试；海外无出口仍保存快照、事件和
  日报，境内通过 QQ、邮箱等既有出口随日报发送。外部投递与数据库提交之间的重复窗口仍在。
- 来源访问失败或表格结构不匹配时返回并记录 warnings，保留已有值，不写零值或猜测值。
  各来源独立失败；人民银行目录不可访问时 LPR 仍可独立更新。
  金融统计主站不可用或未找到报告时，检查[苏州市委金融办的官方转载](https://jrjgj.suzhou.gov.cn/szdfjr/jrsx/nav_list.shtml)，
  严格核对来源为“中国人民银行”及全国报告标题，拒绝混入地方统计或媒体评论。
  `publication_note` 明示转载及其页面发布时间，转载可能滞后；准备金率等其他央行公告
  仍依赖人民银行主站，不能因金融统计备用源正常而声称全部政策公告可达。

查询接口沿用全局 API 密钥配置（`X-API-Key`）：

```text
GET /macro-data/observations?country=CN&series_id=CN.CPI.yoy
GET /macro-data/observations?series_id=US.CES0000000001&period=2026-10&history=true
GET /macro-data/releases?country=US
```

默认返回每个发布/统计期的最新版本；`history=true` 包含已留存的全部修订版本。
`previous_period` 是库中最近的较早统计期，可能跨越缺失月份，必须连同 period 一起读。
`/releases` 还返回政策正文和整份发布的结构化字段。最早历史从首次接入时的官方返回
数据开始，不能重建接入之前未留存的历史版本。

此阶段未接入市场一致预期、预期差、美国 Census 数据和初请失业金等额外来源。
部分央行公告仅有政策正文，不强行将不同机构、不同生效日期的政策合成一个全国利率。
配置见 `config/tasks/default/macro-data.yaml`；`providers: []` 跳过本地抓取，已同步数据仍可进入日报，
`enabled: false` 关闭任务。部署仍按境内先、海外后的顺序更新镜像，保留已有迁移头。

### 统一随日报发送

两个宏观任务的 `source_config.standalone_notifications` 默认且在配置中显式设为 `false`。
它们继续按原频率抓取、生成事件并保存 `skipped` 的采集记录及条目，供同步使用，
即使配置了 QQ 或邮件出口也不会独立推送；不要用 `enabled: false` 代替这个开关，
否则会连采集一起停掉。`important_daily` 按既有日报时间合并发送。

日报只合并最新有效版本，保留完整数值、单位、前期记录和官方来源。它按本地出口及
成功发送的事件记录去重，也识别升级前已经成功发送的独立宏观通知；海外已发送或
采集阶段的 skipped 记录不代表境内已发送。晚到的同步记录及上次发送失败的条目，
在数据三天、预告七天的有效窗口内补入后续日报，不因新闻窗口已经推进而丢失。
已过时的日程和被修订版本替代的旧值不再补发。

## 同步协议与状态

同步仍使用 HTTPS、公钥 pin 和 HMAC 签名，接收进程不连接数据库。

1. 发送端导出 gzip 批次，原子写入 `outbox/`。
2. `POST /upload` 校验身份与签名后落盘，返回 `accepted` 或 `already_present`。同一批次 ID 的不同内容会被拒绝。
3. 境内导入器在数据库事务中导入全部记录。事务提交后，才原子写入 `receipts/<batch_id>.json`，再把批次归档到 `processed/`。
4. 发送端通过 `GET /batches/<batch_id>` 查询回执。这个接口使用与上传相同的 Bearer 和来源身份验证。
5. 只有验证过签名且匹配本地批次 ID、来源和内容签名的 `imported` 回执，才能推进 `cursors.json` 并把批次移入 `sent/`。

接收后的 `pending` 是正常等待状态，下一次定时器继续检查；上传失败、导入失败或回执验证失败不会推进游标，也不会删除待发送批次。导入失败时写入不含 SQL、正文或凭据的签名 `failed` 状态；修复原因后，保留在 inbox 的文件会在下一次导入时重试。

发送器每次最多新建一个批次，先处理已有 outbox 文件。接收端对已归档批次保留回执，重传不会再次创建 inbox 文件。若数据库提交后回执写入失败，下次通过幂等重导恢复；若发送端写游标后归档失败，下次继续确认同一批次。

## 两个独立游标与依赖补齐

- `document_until`：文档观察时间窗口，同时纳入窗口内新建的事件和实体匹配，补齐它们引用的旧文档。
- `digest_until`：日报 `updated_at` 时间窗口，包含无新闻条目的空日报和后来更新的日报。
- 导出的日报会携带全部条目、条目对应事件和原始文档。早已同步的文档随后被日报引用时，依赖记录会再次携带并幂等导入。
- 导入日报记录保存 `source_instance`，出口标识加同步命名空间；境内日报窗口只读取本地生成的日报。较旧批次不会覆盖已导入的较新日报正文。

两种窗口都是左闭右开。发送器默认回看 300 秒，缓解短时提交延迟和时钟偏差，可通过 `WORLDNET_SYNC_OVERLAP_SECONDS` 调整。长事务或超过回看范围的历史缺口需要显式补传。两端应保持时钟同步。

旧版 `last_successful_export` 只用于初始化文档游标，首次升级会从头补齐日报历史。升级后不再更新旧文件。旧 outbox 批次仍可重试，旧批次不推进新游标，下一份自动批次会通过幂等重导补齐。

## 升级与操作

1. 先升级境内，再升级海外。两端都运行 `alembic upgrade head`（现有 `scripts/deploy.sh` 已包含此步骤），再重建应用镜像。新镜像增加 curl，供容器内发送器校验 SPKI pin。
2. 保持原有 `WORLDNET_SYNC_SECRET`、`WORLDNET_SYNC_URL`、`WORLDNET_SYNC_TLS_PIN` 与来源配置。应用 Compose 已转发发送所需环境变量，HTTPS 接收容器仍只获取接收所需变量。
3. 继续使用原来的 push/import systemd 定时器。发送脚本保留宿主机 `flock`，实际导出、重试与回执校验在应用容器内完成。
4. 确保接收进程可以读取同步根目录下的 `receipts/`。不要在发送端确认前清理 outbox、inbox 或回执。首次日报历史回填会根据源批次 ID 给旧导入日报补上来源标识。

手动触发：

```bash
# 海外：上传或重试，并查询导入回执
bash scripts/push_sync_batch.sh

# 境内：导入并生成回执
bash scripts/import_sync_inbox.sh
```

按指定区间补传（示例日期必须替换为需要修复的区间；两种游标单独指定）：

```bash
docker compose run --rm -T app python scripts/export_sync_batch.py \
  --output /var/lib/worldnet-sync/outbox/manual-repair.json.gz \
  --since 2026-08-31T00:00:00Z --until 2026-09-01T00:00:00Z \
  --digest-since 2026-08-31T00:00:00Z --digest-until 2026-09-01T00:00:00Z
```

随后正常运行发送脚本；手动补传批次只补数据，不推进自动同步游标。`--digest-since` 省略时回填全部日报历史。自动批次单独标记为可推进游标，手动补传不会跳过尚未同步的区间。

接收端默认压缩上传上限为 16 MiB，解压后上限为 64 MiB。当前不自动分片；长期停机后的大量回填应使用较小时间区间，并留意单份日报的依赖体积。数据库迁移、事务、协议和重试已有本地测试，生产网络、证书权限和定时器仍需在部署后检查。
