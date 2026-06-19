import json
import os
from typing import Any, Callable, Dict, List

from dotenv import load_dotenv
from google import genai

from app.services.output_filename import resolve_output_name
from app.services.pexels_client import search_pexels
from app.services.pokemon_client import get_pokemon_data
from app.services.time_tool import get_current_time
from app.services.video_producer import (
    produce_lofi_video,
    produce_sound_short_simple,
    produce_text_short_simple,
)
from app.services.weather_client import (
    get_current_weather,
    get_weather_forecast,
)
from app.services.wikipedia_client import search_wikipedia


DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
_tool_results: List[Dict[str, Any]] = []


class AgentConfigurationError(Exception):
    pass


def get_gemini_client() -> genai.Client:
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise AgentConfigurationError("GEMINI_API_KEY is not configured")
    return genai.Client(api_key=api_key)


def get_gemini_model_name() -> str:
    load_dotenv()
    return os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)


def reset_tool_results() -> None:
    global _tool_results
    _tool_results = []


def get_tool_results() -> List[Dict[str, Any]]:
    return list(_tool_results)


def get_tools_used() -> List[str]:
    return sorted({entry["tool"] for entry in _tool_results})


def record_tool_result(
    tool_name: str,
    args: Dict[str, Any],
    result: Any = None,
    error: str | None = None,
) -> None:
    entry: Dict[str, Any] = {"tool": tool_name, "args": args}
    if error is not None:
        entry["error"] = error
    else:
        entry["result"] = result
    _tool_results.append(entry)


def get_researchers_used() -> List[str]:
    """Legacy helper retained for compatibility; research is now unified."""
    return []


def _json_tool_response(
    tool_name: str,
    args: Dict[str, Any],
    action: Callable[[], Any],
) -> str:
    try:
        result = action()
        record_tool_result(tool_name, args, result)
        return json.dumps(result)
    except Exception as exc:
        record_tool_result(tool_name, args, error=str(exc))
        return json.dumps({"error": str(exc)})


def get_current_time_tool(timezone_name: str) -> str:
    """Gets the current date and time in an IANA timezone.

    Args:
        timezone_name: IANA timezone such as UTC, Africa/Johannesburg,
            or America/New_York. Use UTC when no timezone is specified.

    Returns:
        A JSON string with the current local date, time, and day of week.
    """
    normalized_timezone = timezone_name.strip() or "UTC"
    return _json_tool_response(
        "time",
        {"timezone_name": normalized_timezone},
        lambda: get_current_time(normalized_timezone),
    )


def get_weather_tool(location: str, forecast_days: int) -> str:
    """Gets current weather and a daily forecast for a location.

    Args:
        location: City, region, or postal code to look up.
        forecast_days: Number of forecast days to retrieve, from 1 to 7.

    Returns:
        A JSON string with current observations and daily forecast data.
    """
    args = {"location": location, "forecast_days": forecast_days}
    return _json_tool_response(
        "weather",
        args,
        lambda: {
            "current": get_current_weather(location),
            "forecast": get_weather_forecast(location, forecast_days),
        },
    )


def search_wikipedia_tool(query: str, max_sources: int) -> str:
    """Searches English Wikipedia and returns article extracts with citation URLs.

    Args:
        query: Topic, title, person, event, or question to research.
        max_sources: Number of relevant articles to retrieve, from 1 to 5.

    Returns:
        A JSON string containing source extracts and citation metadata.
    """
    args = {"query": query, "max_sources": max_sources}
    return _json_tool_response(
        "wikipedia",
        args,
        lambda: search_wikipedia(query, max_sources),
    )


def get_pokemon_tool(identifier: str) -> str:
    """Gets verified Pokemon data by name or National Pokedex number.

    Args:
        identifier: A Pokemon name or positive National Pokedex number.

    Returns:
        A JSON string containing verified PokeAPI data.
    """
    args = {"identifier": identifier}
    return _json_tool_response(
        "pokemon",
        args,
        lambda: get_pokemon_data(identifier),
    )


def search_pexels_tool(query: str, media_type: str, per_page: int) -> str:
    """Searches Pexels for royalty-free stock photos or videos.

    Args:
        query: Search terms such as 'ocean waves' or 'city night'.
        media_type: Return photo, video, or both.
        per_page: Number of results to return, from 1 to 80. Use 5 for b-roll.

    Returns:
        A JSON string with media URLs, dimensions, duration, and attribution.
    """
    args = {
        "query": query,
        "media_type": media_type,
        "per_page": per_page,
    }
    return _json_tool_response(
        "pexels",
        args,
        lambda: search_pexels(
            query,
            media_type=media_type,
            per_page=per_page,
        ),
    )


def create_text_short_video_tool(text: str) -> str:
    """Creates a silent 9:16 text short video file.

    Args:
        text: On-screen text. Keep under 1000 characters.

    Returns:
        A JSON string with output_path, duration_seconds, and dimensions.
    """
    output_name = resolve_output_name(text, default_stem="text-short")
    args = {"text": text, "output_name": output_name}
    return _json_tool_response(
        "text_short",
        args,
        lambda: produce_text_short_simple(text, output_name),
    )


def create_sound_short_video_tool(text: str) -> str:
    """Creates a narrated 9:16 short with ElevenLabs speech and centered text.

    Args:
        text: Narration and on-screen text. Keep under 2500 characters.

    Returns:
        A JSON string with output_path, duration_seconds, and dimensions.
    """
    output_name = resolve_output_name(text, default_stem="sound-short")
    args = {"text": text, "output_name": output_name}
    return _json_tool_response(
        "sound_short",
        args,
        lambda: produce_sound_short_simple(text, output_name),
    )


def create_lofi_video_tool(
    image_path: str,
    audio_path: str,
    repeat_minutes: int,
) -> str:
    """Creates a longer lofi-style video from a local image and audio file.

    Args:
        image_path: Absolute or relative path to a background image file.
        audio_path: Absolute or relative path to an audio file.
        repeat_minutes: Target loop length from 1 to 180 minutes.

    Returns:
        A JSON string with output_path, duration_seconds, and dimensions.
    """
    output_name = resolve_output_name(image_path, default_stem="lofi")
    args = {
        "image_path": image_path,
        "audio_path": audio_path,
        "repeat_minutes": repeat_minutes,
        "output_name": output_name,
    }
    return _json_tool_response(
        "lofi",
        args,
        lambda: produce_lofi_video(
            image_path=image_path,
            audio_path=audio_path,
            repeat_minutes=repeat_minutes,
            output_name=output_name,
        ),
    )


RESEARCH_TOOLS = [
    get_current_time_tool,
    get_weather_tool,
    search_wikipedia_tool,
    get_pokemon_tool,
    search_pexels_tool,
]

SHORT_VIDEO_TOOLS = [
    create_text_short_video_tool,
    create_sound_short_video_tool,
]

LOFI_TOOLS = [
    create_lofi_video_tool,
]

ALL_TOOLS = [
    *RESEARCH_TOOLS,
    *SHORT_VIDEO_TOOLS,
    *LOFI_TOOLS,
]

TOOL_GROUPS = {
    "research": RESEARCH_TOOLS,
    "short_video": SHORT_VIDEO_TOOLS,
    "lofi": LOFI_TOOLS,
    "all": ALL_TOOLS,
}


def run_tool(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Run a named tool directly and return parsed JSON."""
    tools = {
        "time": get_current_time_tool,
        "weather": get_weather_tool,
        "wikipedia": search_wikipedia_tool,
        "pokemon": get_pokemon_tool,
        "pexels": search_pexels_tool,
        "text_short": create_text_short_video_tool,
        "sound_short": create_sound_short_video_tool,
        "lofi": create_lofi_video_tool,
    }
    tool = tools.get(tool_name)
    if tool is None:
        raise ValueError(
            "tool_name must be one of: "
            "time, weather, wikipedia, pokemon, pexels, "
            "text_short, sound_short, lofi"
        )
    return json.loads(tool(**arguments))
