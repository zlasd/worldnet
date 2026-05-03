"""Pipeline task runner for scheduled/manual execution."""
from app.adapters.factory import build_adapters
from app.db.session import get_db_session
from app.pipelines.runner import run_full_pipeline
from app.utils.logging import get_logger

logger = get_logger(__name__)


def run_pipeline(source: str = "official_announcement") -> dict[str, dict]:
    results: dict[str, dict] = {}
    for adapter in build_adapters(source):
        with get_db_session() as session:
            results[adapter.source_name] = run_full_pipeline(adapter, session)
    logger.info("Pipeline complete for source=%s: %s", source, results)
    return results


def run_announcement_pipeline() -> dict:
    return run_pipeline("official_announcement")["official_announcement"]


def run_rsshub_cls_telegraph_pipeline() -> dict:
    return run_pipeline("rsshub_cls_telegraph")["rsshub_cls_telegraph"]


def run_rsshub_cls_depth_pipeline() -> dict:
    return run_pipeline("rsshub_cls_depth")["rsshub_cls_depth"]


def run_worldnewsapi_pipeline() -> dict:
    return run_pipeline("worldnewsapi_top_news")["worldnewsapi_top_news"]


def run_all_pipelines() -> dict[str, dict]:
    return run_pipeline("all")
