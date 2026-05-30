import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.middleware import SlowAPIMiddleware

from app.core.config import (
    CLEANUP_INTERVAL_SECONDS,
    CORS_ORIGINS,
    OUTPUT_DIR,
    UPLOADS_DIR,
    ensure_directories,
)
from app.core.errors import register_exception_handlers
from app.core.rate_limit import limiter
from app.core.request_logging import RequestLoggingMiddleware
from app.jobs import store
from app.jobs.cleanup import cleanup_expired_data
from app.jobs.queue import close_arq_pool
from app.models.health import HealthPaths, HealthResponse
from app.routers import batch, jobs, lofi, shorts, slideshow

logging.basicConfig()
logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO)
logging.getLogger("uvicorn").setLevel(logging.INFO)
logging.getLogger("app.request").setLevel(logging.INFO)
logger = logging.getLogger(__name__)


async def _cleanup_scheduler() -> None:
    while True:
        try:
            await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
            await asyncio.to_thread(cleanup_expired_data)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Scheduled cleanup failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_directories()
    store.init_db()
    cleanup_task = asyncio.create_task(_cleanup_scheduler())
    yield
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    await close_arq_pool()


app = FastAPI(
    title="FrameFusion API",
    description="Video generation API",
    lifespan=lifespan,
)

register_exception_handlers(app)
app.state.limiter = limiter

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(SlowAPIMiddleware)

app.include_router(jobs.router, prefix="/api/jobs", tags=["Jobs"])
app.include_router(lofi.router, prefix="/api/lofi", tags=["Lofi"])
app.include_router(slideshow.router, prefix="/api/slideshow", tags=["Slideshow"])
app.include_router(shorts.router, prefix="/api/shorts", tags=["Shorts"])
app.include_router(batch.router, prefix="/api/batch", tags=["Batch"])


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        paths=HealthPaths(
            uploads=str(UPLOADS_DIR),
            output=str(OUTPUT_DIR),
        ),
    )
