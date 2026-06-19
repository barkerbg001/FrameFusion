from fastapi import APIRouter, HTTPException, Query

from app.models.tools import TimeData
from app.services.time_tool import get_current_time


router = APIRouter()


@router.get("", response_model=TimeData)
def current_time(
    timezone: str = Query(
        "UTC",
        min_length=1,
        max_length=100,
        description="IANA timezone name",
        examples=["Africa/Johannesburg"],
    ),
) -> TimeData:
    try:
        return TimeData(**get_current_time(timezone))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
