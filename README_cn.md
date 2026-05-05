# WorldNet

WorldNet 是一个面向个人投资研究的事件雷达：抓取公告和新闻，关联股票实体，归一化成结构化事件，再按 watchlist 优先级输出结果。

## 当前能力

- 交易所公告：官方公告源、RSSHub 财联社、RSSHub 上交所/深交所公告
- watchlist 驱动监控：可只监控 watchlist 中的 A 股标的
- 配置化调度：任务通过 YAML 文件定义，支持 `interval_minutes` 或 `cron`
- 部署友好：内置 Dockerfile、`docker-compose.yml` 和升级脚本

## 快速开始

```bash
pip install -e ".[dev]"
python scripts/init_db.py
python scripts/seed_data.py
python scripts/run_pipeline.py
python scripts/list_events.py
uvicorn app.api.main:app --reload
```

## 常用命令

```bash
# 运行内置 source
python scripts/run_pipeline.py --source rsshub_cls_telegraph
python scripts/run_pipeline.py --source rsshub_cls_depth

# 运行参数化交易所公告 source
python scripts/run_pipeline.py --source rsshub_sse_disclosure --source-option product_id=600000 --source-option company_name=浦发银行
python scripts/run_pipeline.py --source rsshub_szse_listed_notice --source-option stock=000001 --source-option company_name=平安银行

# 启动调度器
python scripts/run_scheduler.py
```

## 文档

- [部署与配置说明](docs/deployment_cn.md)
- [架构说明](docs/architecture_cn.md)
