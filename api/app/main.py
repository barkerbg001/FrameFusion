import logging

from fastapi import FastAPI

from app.routers import (lofi, youtube)

# Enable SQLAlchemy query logging for debugging
logging.basicConfig()
logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO)
logging.getLogger("uvicorn").setLevel(logging.INFO)

# Initialize FastAPI application
app = FastAPI()

# Include the authentication and common routers with prefixes
app.include_router(lofi.router, prefix="/api/lofi", tags=["Lofi"])
app.include_router(youtube.router, prefix="/api/youtube", tags=["YouTube"])
