import json
from functools import lru_cache
from typing import Any, Dict, Iterable, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


MEDIAWIKI_API_URL = "https://en.wikipedia.org/w/api.php"


class WikipediaNotFoundError(Exception):
    pass


class WikipediaServiceError(Exception):
    pass


def _request_json(url: str) -> Dict[str, Any]:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "FrameFusion/1.0 (Wikipedia research tool)",
        },
    )
    try:
        with urlopen(request, timeout=15) as response:
            return json.load(response)
    except HTTPError as exc:
        raise WikipediaServiceError(
            f"MediaWiki returned HTTP {exc.code}"
        ) from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise WikipediaServiceError(
            "Unable to retrieve Wikipedia source material"
        ) from exc


@lru_cache(maxsize=512)
def _search_wikipedia_cached(
    normalized_query: str,
    candidate_count: int,
) -> tuple[Dict[str, Any], ...]:
    query = urlencode(
        {
            "action": "query",
            "generator": "search",
            "gsrsearch": normalized_query,
            "gsrnamespace": 0,
            "gsrlimit": candidate_count,
            "prop": "extracts|info",
            "exintro": 1,
            "explaintext": 1,
            "exchars": 4000,
            "inprop": "url",
            "redirects": 1,
            "format": "json",
            "formatversion": 2,
            "origin": "*",
        }
    )
    response = _request_json(f"{MEDIAWIKI_API_URL}?{query}")
    pages = response.get("query", {}).get("pages", [])
    pages.sort(key=lambda page: page.get("index", 9999))
    return tuple(pages)


def search_wikipedia(
    query: str,
    max_sources: int = 3,
    excluded_title_terms: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Search English Wikipedia and return article extracts and citation URLs."""
    normalized = " ".join(query.strip().split())
    if len(normalized) < 2:
        raise ValueError("query must contain at least two characters")
    if max_sources < 1 or max_sources > 5:
        raise ValueError("max_sources must be between 1 and 5")

    excluded = tuple(
        term.lower()
        for term in (excluded_title_terms or ())
        if term.strip()
    )
    candidate_count = min(max(max_sources * 3, 5), 15)
    pages = _search_wikipedia_cached(normalized, candidate_count)
    sources = []

    for page in pages:
        title = page["title"]
        if any(term in title.lower() for term in excluded):
            continue
        extract = " ".join((page.get("extract") or "").split())
        if not extract:
            continue
        sources.append(
            {
                "source_number": len(sources) + 1,
                "title": title,
                "url": page["fullurl"],
                "page_id": page["pageid"],
                "extract": extract,
            }
        )
        if len(sources) == max_sources:
            break

    if not sources:
        raise WikipediaNotFoundError(
            f"No readable Wikipedia sources found for '{normalized}'"
        )
    return {
        "query": normalized,
        "sources": sources,
    }
