from fastapi import APIRouter

from app.core.config import settings

router = APIRouter()

if settings.ENABLE_DATABASE:
    from app.api.v2.endpoints.rankings import router as rankings_router

    router.include_router(rankings_router, prefix="/rankings", tags=["Rankings"])
