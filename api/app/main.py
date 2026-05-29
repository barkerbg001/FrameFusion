import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import CORS_ORIGINS, OUTPUT_DIR, UPLOADS_DIR, ensure_directories
from app.core.errors import register_exception_handlers
from app.core.request_logging import RequestLoggingMiddleware
from app.routers import batch, lofi, shorts, slideshow

logging.basicConfig()
logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO)
logging.getLogger("uvicorn").setLevel(logging.INFO)
logging.getLogger("app.request").setLevel(logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_directories()
    yield


app = FastAPI(
    title="FrameFusion API",
    description="Video generation API",
    lifespan=lifespan,
)

register_exception_handlers(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestLoggingMiddleware)

app.include_router(lofi.router, prefix="/api/lofi", tags=["Lofi"])
app.include_router(slideshow.router, prefix="/api/slideshow", tags=["Slideshow"])
app.include_router(shorts.router, prefix="/api/shorts", tags=["Shorts"])
app.include_router(batch.router, prefix="/api/batch", tags=["Batch"])


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "paths": {
            "uploads": str(UPLOADS_DIR),
            "output": str(OUTPUT_DIR),
        },
    }
