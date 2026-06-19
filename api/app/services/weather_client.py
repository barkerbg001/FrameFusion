import json
from functools import lru_cache
from typing import Any, Dict
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

WEATHER_CONDITIONS = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snowfall",
    73: "Moderate snowfall",
    75: "Heavy snowfall",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


class LocationNotFoundError(Exception):
    pass


class WeatherServiceError(Exception):
    pass


def _request_json(url: str) -> Dict[str, Any]:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "FrameFusion/1.0",
        },
    )

    try:
        with urlopen(request, timeout=10) as response:
            return json.load(response)
    except HTTPError as exc:
        raise WeatherServiceError(
            f"Weather provider returned HTTP {exc.code}"
        ) from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise WeatherServiceError("Unable to retrieve weather data") from exc


@lru_cache(maxsize=256)
def _find_location(location: str) -> Dict[str, Any]:
    query = urlencode(
        {
            "name": location,
            "count": 1,
            "language": "en",
            "format": "json",
        }
    )
    response = _request_json(f"{GEOCODING_URL}?{query}")
    results = response.get("results") or []
    if not results:
        raise LocationNotFoundError(f"Location '{location}' was not found")
    return results[0]


def get_current_weather(location: str) -> Dict[str, Any]:
    """Return current weather for a city, place name, or postal code."""
    normalized = " ".join(location.strip().split())
    if len(normalized) < 2:
        raise ValueError("location must contain at least two characters")

    place = _find_location(normalized.lower())
    current_variables = ",".join(
        (
            "temperature_2m",
            "relative_humidity_2m",
            "apparent_temperature",
            "is_day",
            "precipitation",
            "weather_code",
            "cloud_cover",
            "wind_speed_10m",
            "wind_direction_10m",
            "wind_gusts_10m",
        )
    )
    query = urlencode(
        {
            "latitude": place["latitude"],
            "longitude": place["longitude"],
            "current": current_variables,
            "timezone": place["timezone"],
            "temperature_unit": "celsius",
            "wind_speed_unit": "kmh",
            "precipitation_unit": "mm",
        }
    )
    response = _request_json(f"{FORECAST_URL}?{query}")
    current = response.get("current")
    if not current:
        raise WeatherServiceError("Weather provider returned no current data")

    weather_code = int(current["weather_code"])
    return {
        "location": {
            "name": place["name"],
            "region": place.get("admin1"),
            "country": place["country"],
            "country_code": place["country_code"],
            "latitude": place["latitude"],
            "longitude": place["longitude"],
            "timezone": place["timezone"],
        },
        "observed_at": current["time"],
        "condition": WEATHER_CONDITIONS.get(
            weather_code,
            "Unknown conditions",
        ),
        "weather_code": weather_code,
        "temperature_celsius": current["temperature_2m"],
        "apparent_temperature_celsius": current["apparent_temperature"],
        "relative_humidity_percent": current["relative_humidity_2m"],
        "precipitation_millimetres": current["precipitation"],
        "cloud_cover_percent": current["cloud_cover"],
        "wind_speed_kmh": current["wind_speed_10m"],
        "wind_direction_degrees": current["wind_direction_10m"],
        "wind_gusts_kmh": current["wind_gusts_10m"],
        "is_day": bool(current["is_day"]),
    }


def get_weather_forecast(
    location: str,
    forecast_days: int = 3,
) -> Dict[str, Any]:
    """Return a daily weather forecast for a location."""
    normalized = " ".join(location.strip().split())
    if len(normalized) < 2:
        raise ValueError("location must contain at least two characters")
    if forecast_days < 1 or forecast_days > 7:
        raise ValueError("forecast_days must be between 1 and 7")

    place = _find_location(normalized.lower())
    daily_variables = ",".join(
        (
            "weather_code",
            "temperature_2m_max",
            "temperature_2m_min",
            "apparent_temperature_max",
            "apparent_temperature_min",
            "sunrise",
            "sunset",
            "precipitation_sum",
            "precipitation_probability_max",
            "wind_speed_10m_max",
            "wind_gusts_10m_max",
        )
    )
    query = urlencode(
        {
            "latitude": place["latitude"],
            "longitude": place["longitude"],
            "daily": daily_variables,
            "forecast_days": forecast_days,
            "timezone": place["timezone"],
            "temperature_unit": "celsius",
            "wind_speed_unit": "kmh",
            "precipitation_unit": "mm",
        }
    )
    response = _request_json(f"{FORECAST_URL}?{query}")
    daily = response.get("daily")
    if not daily:
        raise WeatherServiceError("Weather provider returned no forecast data")

    days = []
    for index, date in enumerate(daily["time"]):
        weather_code = int(daily["weather_code"][index])
        days.append(
            {
                "date": date,
                "condition": WEATHER_CONDITIONS.get(
                    weather_code,
                    "Unknown conditions",
                ),
                "weather_code": weather_code,
                "temperature_max_celsius": daily[
                    "temperature_2m_max"
                ][index],
                "temperature_min_celsius": daily[
                    "temperature_2m_min"
                ][index],
                "apparent_temperature_max_celsius": daily[
                    "apparent_temperature_max"
                ][index],
                "apparent_temperature_min_celsius": daily[
                    "apparent_temperature_min"
                ][index],
                "sunrise": daily["sunrise"][index],
                "sunset": daily["sunset"][index],
                "precipitation_millimetres": daily[
                    "precipitation_sum"
                ][index],
                "precipitation_probability_percent": daily[
                    "precipitation_probability_max"
                ][index],
                "wind_speed_max_kmh": daily[
                    "wind_speed_10m_max"
                ][index],
                "wind_gusts_max_kmh": daily[
                    "wind_gusts_10m_max"
                ][index],
            }
        )

    return {
        "location": {
            "name": place["name"],
            "region": place.get("admin1"),
            "country": place["country"],
            "country_code": place["country_code"],
            "latitude": place["latitude"],
            "longitude": place["longitude"],
            "timezone": place["timezone"],
        },
        "forecast_days": days,
    }
