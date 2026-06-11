import json
import os
from datetime import datetime, timezone
from typing import Any, Dict

from dotenv import load_dotenv
from google import genai
from google.genai import types

from app.models.tools import WeatherResearchReport
from app.services.weather_client import (
    get_current_weather,
    get_weather_forecast,
)


DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"


class WeatherAgentError(Exception):
    pass


def research_weather_tool(
    location: str,
    forecast_days: int,
) -> str:
    """Gets current weather and a multi-day forecast for a location.

    Args:
        location: City, region, or postal code to research.
        forecast_days: Number of forecast days to retrieve, from 1 to 7.

    Returns:
        A JSON string containing current observations and daily forecast data.
    """
    data = {
        "current": get_current_weather(location),
        "forecast": get_weather_forecast(location, forecast_days),
    }
    return json.dumps(data)


def research_weather(
    location: str,
    question: str = "Provide a practical weather briefing.",
    forecast_days: int = 3,
) -> Dict[str, Any]:
    """Run the Gemini weather researcher and return a structured report."""
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise WeatherAgentError("GEMINI_API_KEY is not configured")

    model = os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
    client = genai.Client(api_key=api_key)
    researched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    research_prompt = f"""
You are FrameFusion's weather research agent.

Research the weather for: {location}
Forecast period: {forecast_days} day(s)
User's question: {question}

You must call research_weather_tool before answering. Base every weather claim
on its returned data. Do not invent alerts, certainty, or meteorological data.
Explain practical implications without presenting medical, emergency, aviation,
marine, or agricultural advice as authoritative. Write a concise research
draft that another step can convert into a structured report.
"""

    try:
        research_response = client.models.generate_content(
            model=model,
            contents=research_prompt,
            config=types.GenerateContentConfig(
                tools=[research_weather_tool],
                tool_config=types.ToolConfig(
                    function_calling_config=types.FunctionCallingConfig(
                        mode="AUTO",
                    )
                ),
                temperature=0.2,
            ),
        )
        weather_data = json.loads(
            research_weather_tool(location, forecast_days)
        )
        format_prompt = f"""
Convert the weather research below into the required response schema.

Location requested: {location}
Question: {question}
Researched at UTC: {researched_at}
Research draft:
{research_response.text}

Authoritative source data:
{json.dumps(weather_data)}

Requirements:
- Set source to "Open-Meteo".
- Preserve the source data exactly in weather_data.
- Include one forecast_outlook item for each forecast day.
- Use empty lists when no meaningful risks or recommendations exist.
- State that this is model forecast data and not an official severe-weather
  warning service in limitations.
"""
        response = client.models.generate_content(
            model=model,
            contents=format_prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=WeatherResearchReport,
                temperature=0,
            ),
        )
        report = WeatherResearchReport.model_validate_json(response.text)
        report.location = weather_data["current"]["location"]["name"]
        report.researched_at = researched_at
        report.source = "Open-Meteo"
        report.weather_data = weather_data
        return report.model_dump()
    except Exception as exc:
        raise WeatherAgentError(
            f"Weather research agent failed: {exc}"
        ) from exc
