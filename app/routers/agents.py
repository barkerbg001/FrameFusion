from fastapi import APIRouter, HTTPException

from app.agents.anime_researcher import AnimeAgentError, research_anime
from app.agents.history_researcher import (
    HistoryAgentError,
    research_history,
)
from app.models.anime import AnimeResearchReport, AnimeResearchRequest
from app.agents.pokemon_researcher import (
    PokemonAgentError,
    research_pokemon,
)
from app.agents.weather_researcher import (
    WeatherAgentError,
    research_weather,
)
from app.models.history import HistoryResearchReport, HistoryResearchRequest
from app.models.pokemon import PokemonResearchReport, PokemonResearchRequest
from app.models.tools import WeatherResearchReport, WeatherResearchRequest
from app.services.pokemon_client import (
    PokemonNotFoundError,
    PokemonServiceError,
)
from app.services.history_client import (
    HistoryNotFoundError,
    HistoryServiceError,
)
from app.services.weather_client import (
    LocationNotFoundError,
    WeatherServiceError,
)
from app.services.wikipedia_client import (
    WikipediaNotFoundError,
    WikipediaServiceError,
)


router = APIRouter()


@router.post(
    "/anime-research",
    response_model=AnimeResearchReport,
)
def anime_research_agent(
    request: AnimeResearchRequest,
) -> AnimeResearchReport:
    try:
        return AnimeResearchReport(
            **research_anime(
                title=request.title,
                question=request.question,
                max_sources=request.max_sources,
                allow_spoilers=request.allow_spoilers,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except WikipediaNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WikipediaServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except AnimeAgentError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post(
    "/history-research",
    response_model=HistoryResearchReport,
)
def history_research_agent(
    request: HistoryResearchRequest,
) -> HistoryResearchReport:
    try:
        return HistoryResearchReport(
            **research_history(
                topic=request.topic,
                question=request.question,
                max_sources=request.max_sources,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HistoryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except HistoryServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except HistoryAgentError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post(
    "/pokemon-research",
    response_model=PokemonResearchReport,
)
def pokemon_research_agent(
    request: PokemonResearchRequest,
) -> PokemonResearchReport:
    try:
        return PokemonResearchReport(
            **research_pokemon(
                identifier=request.identifier,
                question=request.question,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PokemonNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"Pokemon '{request.identifier}' was not found",
        ) from exc
    except PokemonServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except PokemonAgentError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post(
    "/weather-research",
    response_model=WeatherResearchReport,
)
def weather_research_agent(
    request: WeatherResearchRequest,
) -> WeatherResearchReport:
    try:
        return WeatherResearchReport(
            **research_weather(
                location=request.location,
                question=request.question,
                forecast_days=request.forecast_days,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LocationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WeatherServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except WeatherAgentError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
