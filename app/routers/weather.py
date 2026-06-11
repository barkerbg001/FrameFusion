from fastapi import APIRouter, HTTPException, Query

from app.models.tools import WeatherData
from app.services.weather_client import (
    LocationNotFoundError,
    WeatherServiceError,
    get_current_weather,
)


router = APIRouter()


@router.get("", response_model=WeatherData)
def current_weather(
    location: str = Query(
        ...,
        min_length=2,
        max_length=150,
        description="City, place name, or postal code",
        examples=["Johannesburg"],
    ),
) -> WeatherData:
    try:
        return WeatherData(**get_current_weather(location))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LocationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WeatherServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
