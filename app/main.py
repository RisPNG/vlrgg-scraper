import logging
import socket
from collections.abc import AsyncIterator, Callable
from contextlib import AsyncExitStack, asynccontextmanager

import redis.asyncio as redis
import sentry_sdk
from arq.connections import RedisSettings
from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.gzip import GZipMiddleware

from app import exceptions, i18n
from app.api import deps
from app.api.v1.api import router
from app.api.v2.api import router as api_v2_router
from app.core import connections
from app.core.config import settings
from app.core.observability import configure_logging, init_sentry
from app.web.media import router as media_router

logger = logging.getLogger(__name__)

configure_logging()
init_sentry()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator:
    logger.info("Creating shared HTTP client")
    try:
        async with AsyncExitStack() as resources:
            connections.http_client = await resources.enter_async_context(connections.get_http_client())
            if settings.ENABLE_DATABASE:
                from app.db.lifecycle import start_database, stop_database

                await start_database()
                resources.push_async_callback(stop_database)
            if settings.ENABLE_LIVE_PUSH:
                from app.core.live_push import start_live_push, stop_live_push

                resources.push_async_callback(stop_live_push)
                await start_live_push()
            if settings.needs_redis:
                logger.info("Connecting to redis")
                connections.redis_pool = redis.ConnectionPool(
                    host=settings.REDIS_HOST,
                    password=settings.REDIS_PASSWORD,
                    port=settings.REDIS_PORT,
                )
                resources.push_async_callback(connections.redis_pool.aclose)
                if settings.ENABLE_CACHE or settings.ENABLE_LIVE_PUSH:
                    from app.cron import arq_worker

                    logger.info("Starting arq worker")
                    resources.push_async_callback(arq_worker.stop)
                    await arq_worker.start(
                        handle_signals=False,
                        redis_settings=RedisSettings(
                            host=settings.REDIS_HOST,
                            port=settings.REDIS_PORT,
                            password=settings.REDIS_PASSWORD,
                        ),
                    )
            yield
    finally:
        connections.redis_pool = None
        connections.http_client = None


app = FastAPI(
    title="Scraper",
    description="Scraper for VLR.gg that exposes a REST API for some data available there",
    lifespan=lifespan,
)
app.add_middleware(GZipMiddleware, minimum_size=500)  # type: ignore[arg-type]
exceptions.register_exception_handlers(app)

_HOSTNAME = socket.gethostname()


@app.middleware("http")
async def add_server_name_header(request: Request, call_next: Callable) -> Response:
    response = await call_next(request)
    response.headers["X-Server"] = _HOSTNAME
    return response


app.middleware("http")(i18n.localize_response)


@app.get("/health", tags=["Health"])
async def health() -> dict[str, str]:
    """Report that the API process is running."""
    return {"status": "ok"}


app.include_router(media_router)

api_dependencies = [Depends(deps.verify_token)] if settings.API_KEYS else []
app.include_router(router, prefix="/api/v1", dependencies=api_dependencies)
app.include_router(api_v2_router, prefix="/api/v2", dependencies=api_dependencies)
if not settings.API_KEYS:
    sentry_sdk.set_tag("api_key", "Unauthenticated")

if settings.ENABLE_LIVE_PUSH and settings.VIDEO_TOKEN_FILE:
    from app.api.v1.endpoints.video import router as video_router

    app.include_router(video_router, prefix="/api/v1/video", dependencies=[Depends(deps.verify_video_token)])

if settings.ENABLE_ID_MAPPING and settings.INTERNAL_API_KEY:
    from app.api.v1.endpoints.internal import router as internal_router

    app.include_router(internal_router, prefix="/api/v1/internal", dependencies=[Depends(deps.verify_internal_token)])
