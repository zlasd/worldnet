from fastapi import Depends, FastAPI

from app.api.deps import require_api_key
from app.api.routes import documents, events, health, instruments, watchlists
from app.core.config import settings

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    dependencies=[Depends(require_api_key)],
)

app.include_router(health.router, tags=["health"])
app.include_router(events.router, prefix="/events", tags=["events"])
app.include_router(documents.router, prefix="/documents", tags=["documents"])
app.include_router(watchlists.router, prefix="/watchlists", tags=["watchlists"])
app.include_router(instruments.router, prefix="/instruments", tags=["instruments"])
