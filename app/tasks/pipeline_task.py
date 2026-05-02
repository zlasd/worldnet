"""Pipeline task runner for scheduled/manual execution."""
from app.adapters.official_announcement_adapter import OfficialAnnouncementAdapter
from app.db.session import get_db_session
from app.pipelines.runner import run_full_pipeline
from app.utils.logging import get_logger

logger = get_logger(__name__)


def run_announcement_pipeline() -> dict:
    adapter = OfficialAnnouncementAdapter()
    with get_db_session() as session:
        result = run_full_pipeline(adapter, session)
    logger.info("Pipeline complete: %s", result)
    return result
