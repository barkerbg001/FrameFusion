from fastapi import APIRouter, HTTPException, Query

from app.services.wikipedia_client import (
    WikipediaNotFoundError,
    WikipediaServiceError,
    search_wikipedia,
)


router = APIRouter()


@router.get("/search")
def wikipedia_search(
    query: str = Query(..., min_length=2, max_length=300),
    max_sources: int = Query(3, ge=1, le=5),
) -> dict:
    try:
        return search_wikipedia(query, max_sources)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except WikipediaNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WikipediaServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
