from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class TimeData(BaseModel):
    timezone: str
    date: str
    time: str
    day_of_week: str
    iso_datetime: str
    utc_offset: str


class WeatherLocation(BaseModel):
    name: str
    region: Optional[str] = None
    country: str
    country_code: str
    latitude: float
    longitude: float
    timezone: str


class WeatherData(BaseModel):
    location: WeatherLocation
    observed_at: str
    condition: str
    weather_code: int
    temperature_celsius: float
    apparent_temperature_celsius: float
    relative_humidity_percent: int
    precipitation_millimetres: float
    cloud_cover_percent: int
    wind_speed_kmh: float
    wind_direction_degrees: int
    wind_gusts_kmh: float
    is_day: bool


class WeatherResearchRequest(BaseModel):
    location: str = Field(..., min_length=2, max_length=150)
    question: str = Field(
        "Provide a practical weather briefing.",
        min_length=1,
        max_length=1000,
    )
    forecast_days: int = Field(3, ge=1, le=7)


class WeatherResearchReport(BaseModel):
    location: str
    researched_at: str
    summary: str
    current_conditions: str
    forecast_outlook: List[str]
    risks: List[str]
    recommendations: List[str]
    limitations: List[str]
    source: str
    weather_data: Dict[str, Any]
