import logging

from fastapi import FastAPI

from app.routers import (
    agents,
    lofi,
    pokemon,
    shorts,
    time,
    weather,
    wikipedia,
    youtube,
)

# Enable SQLAlchemy query logging for debugging
logging.basicConfig()
logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO)
logging.getLogger("uvicorn").setLevel(logging.INFO)

# Initialize FastAPI application
app = FastAPI()

# Include the authentication and common routers with prefixes
app.include_router(agents.router, prefix="/api/agents", tags=["Agents"])
app.include_router(lofi.router, prefix="/api/lofi", tags=["Lofi"])
app.include_router(pokemon.router, prefix="/api/pokemon", tags=["Pokemon"])
app.include_router(shorts.router, prefix="/api/shorts", tags=["Shorts"])
app.include_router(time.router, prefix="/api/time", tags=["Time"])
app.include_router(weather.router, prefix="/api/weather", tags=["Weather"])
app.include_router(
    wikipedia.router,
    prefix="/api/wikipedia",
    tags=["Wikipedia"],
)
app.include_router(youtube.router, prefix="/api/youtube", tags=["YouTube"])
