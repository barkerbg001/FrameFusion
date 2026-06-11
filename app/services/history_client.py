from typing import Any, Dict

from app.services.wikipedia_client import (
    WikipediaNotFoundError,
    WikipediaServiceError,
    search_wikipedia,
)


HistoryNotFoundError = WikipediaNotFoundError
HistoryServiceError = WikipediaServiceError

HISTORY_EXCLUDED_TITLE_TERMS = (
    "disambiguation",
    " documentary)",
    " film)",
    " miniseries)",
    " novel)",
    " song)",
    " tv series)",
    " video game)",
)


def research_history_sources(
    topic: str,
    max_sources: int,
) -> Dict[str, Any]:
    """Search Wikipedia and return extracts with citation metadata."""
    return search_wikipedia(
        query=topic,
        max_sources=max_sources,
        excluded_title_terms=HISTORY_EXCLUDED_TITLE_TERMS,
    )
