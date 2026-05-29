import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import OUTPUT_DIR, UPLOADS_DIR, ensure_directories
from app.routers import lofi, youtube

logging.basicConfig()
logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO)
logging.getLogger("uvicorn").setLevel(logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_directories()
    yield


app = FastAPI(
    title="FrameFusion API",
    description="Video generation API",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(lofi.router, prefix="/api/lofi", tags=["Lofi"])
app.include_router(youtube.router, prefix="/api/youtube", tags=["YouTube"])


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "paths": {
            "uploads": str(UPLOADS_DIR),
            "output": str(OUTPUT_DIR),
        },
    }
