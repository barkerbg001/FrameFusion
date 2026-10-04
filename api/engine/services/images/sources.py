"""Image search adapters.

Licensed sources (automatic selection may use these):

* Pexels (``/v1/search``) needs the Pexels key from Settings; every photo is
  under the Pexels License (https://www.pexels.com/license/).
* Pixabay (``GET https://pixabay.com/api/``) needs the Pixabay key from
  Settings; content is under the Pixabay Content License
  (https://pixabay.com/service/license-summary/). The API terms require caching
  identical requests for 24 hours, no permanent hotlinking (images are
  downloaded into the project) and showing where results come from. Limit:
  100 requests per 60 seconds.
* Wikimedia Commons (MediaWiki Action API, ``prop=imageinfo&iiprop=extmetadata``)
  needs no key but requires a descriptive User-Agent. Each file's licence comes
  from its own metadata; only free licences that allow modification are kept
  (CC0, public domain, CC BY, CC BY-SA). Strong for named places, people,
  species, artworks and diagrams.
* Openverse (``GET https://api.openverse.org/v1/images/``) needs no key. It
  indexes openly licensed images and reports each image's licence. Anonymous
  use is rate limited, so a 429 is a limitation rather than a retry loop.

Discovery only (reuse rights unknown, never selected automatically):

* Brave Image Search (``GET https://api.search.brave.com/res/v1/images/search``)
  needs a Brave Search API key (paid per request). Results point to images on
  arbitrary websites, so they are offered to the user for review.
* A direct image URL or a public web page the user supplied.

FrameFusion never claims reuse rights; it reports the licence the source gives.
"""

from __future__ import annotations

import hashlib
import html
import re
import threading
import time
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx

from engine import integrations
from engine.services import pexels_client
from engine.services.images import safe_fetch
from engine.services.images.brief import VisualBrief
from engine.services.images.candidates import ImageCandidate, clean_text
from engine.services.images.webpage import extract_candidates

Orientation = Literal["portrait", "landscape", "square"]
Source = Literal["auto", "pexels", "pixabay", "wikimedia", "openverse", "brave", "url", "webpage"]
SEARCH_SOURCES: tuple[str, ...] = (
    "auto",
    "pexels",
    "pixabay",
    "wikimedia",
    "openverse",
    "brave",
    "url",
    "webpage",
)
LICENSED_SOURCES = ("pexels", "pixabay", "wikimedia", "openverse")

OPENVERSE_URL = "https://api.openverse.org/v1/images/"
OPENVERSE_LICENSES = "by,by-sa,cc0,pdm"
PEXELS_LICENSE_URL = "https://www.pexels.com/license/"
PEXELS_NOTE = (
    "Pexels License: free to use and modify, attribution appreciated. It does not cover "
    "identifiable people or brands in endorsements or selling unaltered copies; check the licence."
)
PIXABAY_URL = "https://pixabay.com/api/"
PIXABAY_LICENSE_URL = "https://pixabay.com/service/license-summary/"
PIXABAY_NOTE = (
    "Pixabay Content License: free to use and modify without attribution. It does not cover "
    "selling unaltered copies, or identifiable people, brands or trademarks in ways that imply "
    "endorsement; check the licence."
)
PIXABAY_CACHE_SECONDS = 24 * 3600
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
COMMONS_DOWNLOAD_WIDTH = 1280
COMMONS_PREVIEW_WIDTH = 500
BRAVE_URL = "https://api.search.brave.com/res/v1/images/search"
BRAVE_NOTE = (
    "Found by Brave image search on a third-party website. Reuse rights are unknown: only use "
    "it if you own it or have permission, and check the source page."
)
OPENVERSE_ASPECT = {"portrait": "tall", "landscape": "wide", "square": "square"}
LICENSE_NAMES = {
    "by": "CC BY",
    "by-sa": "CC BY-SA",
    "by-nd": "CC BY-ND",
    "by-nc": "CC BY-NC",
    "by-nc-sa": "CC BY-NC-SA",
    "by-nc-nd": "CC BY-NC-ND",
    "cc0": "CC0",
    "pdm": "Public Domain Mark",
}
# Commons licences that allow reuse with modification (cropping) in any context.
_FREE_COMMONS = re.compile(
    r"^(cc0|cc[- ]zero|public domain|pd\b|pd-|cc[- ]by(-sa)?(\s|$|[- ]\d)|attribution\b)",
    re.IGNORECASE,
)
_RESTRICTIVE_COMMONS = re.compile(r"\b(nc|nd|non-?commercial|no ?deriv|fair use|non-?free)\b", re.I)


class ImageSearchError(Exception):
    def __init__(self, message: str, source: str, *, kind: str = "search_failed") -> None:
        super().__init__(message)
        self.source = source
        self.kind = kind


def available(source: str) -> bool:
    if source in ("pexels", "pixabay", "brave"):
        return integrations.is_configured(source)  # type: ignore[arg-type]
    return True


def pexels_available() -> bool:
    return available("pexels")


def _json_client(headers: dict[str, str] | None = None) -> httpx.Client:
    return httpx.Client(
        transport=safe_fetch.TRANSPORT,
        timeout=httpx.Timeout(20.0, connect=8.0),
        trust_env=False,
        headers={
            "User-Agent": safe_fetch.USER_AGENT,
            "Accept": "application/json",
            **(headers or {}),
        },
    )


# --- Pexels -----------------------------------------------------------------------------


def _pexels_download_url(original: str) -> str:
    # Pexels' CDN resizes on request; 2200px on the long side is plenty for 1080x1920.
    return f"{original}?auto=compress&cs=tinysrgb&h=2200"


def search_pexels(query: str, orientation: Orientation | None, limit: int) -> list[ImageCandidate]:
    try:
        result = pexels_client.search_pexels_photos(
            query, per_page=max(1, min(limit, 30)), orientation=orientation, size=None
        )
    except pexels_client.PexelsNotFoundError:
        return []
    except integrations.IntegrationNotConfigured as exc:
        raise ImageSearchError(
            "Pexels isn't set up. Add a key in Settings.", "pexels", kind="not_configured"
        ) from exc
    except pexels_client.PexelsServiceError as exc:
        raise ImageSearchError(str(exc), "pexels") from exc
    candidates = []
    for photo in result.get("photos", []):
        source = photo.get("src") or {}
        original = source.get("original")
        if not original:
            continue
        candidates.append(
            ImageCandidate(
                candidate_id=f"pexels:{photo['id']}",
                provider="pexels",
                title=clean_text(photo.get("alt") or "", 200),
                preview_url=source.get("medium") or source.get("small"),
                download_url=_pexels_download_url(original),
                source_page_url=photo.get("url"),
                width=photo.get("width"),
                height=photo.get("height"),
                format="jpeg",
                creator=clean_text(photo.get("photographer") or "", 120) or None,
                creator_url=photo.get("photographer_url"),
                license="Pexels License",
                license_url=PEXELS_LICENSE_URL,
                attribution=photo.get("attribution"),
                rights_status="documented",
                usage_note=PEXELS_NOTE,
            )
        )
    return candidates


# --- Pixabay ----------------------------------------------------------------------------

_pixabay_lock = threading.Lock()
_pixabay_cache: dict[tuple[Any, ...], tuple[float, list[dict[str, Any]]]] = {}


def clear_caches() -> None:
    with _pixabay_lock:
        _pixabay_cache.clear()


def _pixabay_hits(params: dict[str, Any]) -> list[dict[str, Any]]:
    key = integrations.get_key("pixabay")
    if not key:
        raise ImageSearchError(
            "Pixabay isn't set up. Add a key in Settings.", "pixabay", kind="not_configured"
        )
    cache_key = tuple(sorted(params.items()))
    now = time.monotonic()
    with _pixabay_lock:
        cached = _pixabay_cache.get(cache_key)
        if cached and now - cached[0] < PIXABAY_CACHE_SECONDS:
            return cached[1]
    try:
        with _json_client() as client:
            response = client.get(PIXABAY_URL, params={**params, "key": key})
    except httpx.HTTPError as exc:
        raise ImageSearchError("Pixabay could not be reached.", "pixabay") from exc
    if response.status_code == 429:
        raise ImageSearchError(
            "Pixabay rate limit reached (100 searches a minute). Try again shortly.",
            "pixabay",
            kind="rate_limited",
        )
    if response.status_code in (400, 401, 403) and "key" in response.text.lower():
        raise ImageSearchError(
            "Pixabay rejected the API key. Check it in Settings.",
            "pixabay",
            kind="invalid_credentials",
        )
    if response.status_code >= 400:
        raise ImageSearchError(f"Pixabay answered with HTTP {response.status_code}.", "pixabay")
    try:
        hits = [hit for hit in response.json().get("hits") or [] if isinstance(hit, dict)]
    except ValueError as exc:
        raise ImageSearchError("Pixabay sent an unreadable response.", "pixabay") from exc
    with _pixabay_lock:
        _pixabay_cache[cache_key] = (now, hits)
        if len(_pixabay_cache) > 300:
            oldest = min(_pixabay_cache, key=lambda item: _pixabay_cache[item][0])
            _pixabay_cache.pop(oldest, None)
    return hits


def search_pixabay(
    query: str, orientation: Orientation | None, limit: int, *, image_type: str = "photo"
) -> list[ImageCandidate]:
    params: dict[str, Any] = {
        "q": query[:100],
        "image_type": image_type if image_type in ("photo", "illustration", "vector") else "all",
        "safesearch": "true",
        "per_page": max(3, min(limit, 30)),
    }
    if orientation in ("portrait", "landscape"):
        params["orientation"] = "vertical" if orientation == "portrait" else "horizontal"
    candidates = []
    for hit in _pixabay_hits(params)[:limit]:
        download = hit.get("largeImageURL") or hit.get("webformatURL")
        if not download or not hit.get("id"):
            continue
        width, height = hit.get("imageWidth"), hit.get("imageHeight")
        if width and height and download == hit.get("largeImageURL"):
            scale = min(1.0, 1280 / max(width, height))
            width, height = round(width * scale), round(height * scale)
        user = clean_text(hit.get("user") or "", 80)
        user_id = hit.get("user_id")
        candidates.append(
            ImageCandidate(
                candidate_id=f"pixabay:{hit['id']}",
                provider="pixabay",
                title=clean_text(str(hit.get("tags") or ""), 200),
                preview_url=hit.get("webformatURL") or hit.get("previewURL"),
                download_url=download,
                source_page_url=hit.get("pageURL"),
                width=width,
                height=height,
                creator=user or None,
                creator_url=f"https://pixabay.com/users/{user}-{user_id}/"
                if user and user_id
                else None,
                license="Pixabay Content License",
                license_url=PIXABAY_LICENSE_URL,
                attribution=f"Image by {user} from Pixabay" if user else "Image from Pixabay",
                rights_status="documented",
                usage_note=PIXABAY_NOTE,
                tags=[clean_text(tag, 40) for tag in str(hit.get("tags") or "").split(",")[:10]],
            )
        )
    return candidates


# --- Wikimedia Commons ------------------------------------------------------------------

_TAG = re.compile(r"<[^>]+>")


def _plain(value: Any, limit: int) -> str:
    text = value.get("value", "") if isinstance(value, dict) else value
    return clean_text(html.unescape(_TAG.sub(" ", str(text or ""))), limit)


def _commons_license(meta: dict[str, Any]) -> tuple[str, str | None] | None:
    if _plain(meta.get("NonFree"), 10).lower() in ("true", "1", "yes"):
        return None
    label = _plain(meta.get("LicenseShortName"), 80) or _plain(meta.get("UsageTerms"), 80)
    if not label or _RESTRICTIVE_COMMONS.search(label) or not _FREE_COMMONS.search(label):
        return None
    return label, _plain(meta.get("LicenseUrl"), 300) or None


def _commons_item(page: dict[str, Any]) -> ImageCandidate | None:
    info = (page.get("imageinfo") or [None])[0]
    if not isinstance(info, dict):
        return None
    mime = str(info.get("mime") or "")
    if mime not in ("image/jpeg", "image/png", "image/webp", "image/svg+xml", "image/tiff"):
        return None
    meta = info.get("extmetadata") or {}
    licence = _commons_license(meta)
    if licence is None:
        return None
    label, license_url = licence
    download = info.get("thumburl") or (
        info.get("url") if mime in ("image/jpeg", "image/png") else None
    )
    if not download:
        return None
    width = info.get("thumbwidth") or info.get("width")
    height = info.get("thumbheight") or info.get("height")
    preview = str(download).replace(f"/{COMMONS_DOWNLOAD_WIDTH}px-", f"/{COMMONS_PREVIEW_WIDTH}px-")
    file_title = str(page.get("title") or "").removeprefix("File:")
    name = _plain(meta.get("ObjectName"), 200) or file_title.rsplit(".", 1)[0]
    artist = _plain(meta.get("Artist"), 160) or None
    restrictions = _plain(meta.get("Restrictions"), 120)
    note = f"{label} per its Wikimedia Commons file page. Credit the author as shown there."
    if restrictions:
        note += f" Other restrictions noted: {restrictions}."
    categories = [
        clean_text(item, 40) for item in _plain(meta.get("Categories"), 600).split("|")[:10] if item
    ]
    return ImageCandidate(
        candidate_id=f"wikimedia:{page.get('pageid')}",
        provider="wikimedia",
        title=clean_text(name, 200),
        description=_plain(meta.get("ImageDescription"), 400),
        preview_url=preview,
        download_url=str(download),
        source_page_url=info.get("descriptionurl"),
        width=width,
        height=height,
        creator=artist,
        license=label,
        license_url=license_url,
        attribution=clean_text(
            f"{name} by {artist or 'unknown author'}, {label}, via Wikimedia Commons", 400
        ),
        rights_status="documented",
        usage_note=note,
        tags=categories,
    )


def search_wikimedia(query: str, limit: int, *, drawings: bool = False) -> list[ImageCandidate]:
    params = {
        "action": "query",
        "format": "json",
        "formatversion": "2",
        "generator": "search",
        "gsrsearch": f"{query} filetype:{'drawing' if drawings else 'bitmap'}",
        "gsrnamespace": "6",
        "gsrlimit": str(max(1, min(limit * 2, 30))),
        "prop": "imageinfo",
        "iiprop": "url|size|mime|extmetadata",
        "iiurlwidth": str(COMMONS_DOWNLOAD_WIDTH),
        "iiextmetadatafilter": (
            "ObjectName|ImageDescription|Artist|LicenseShortName|LicenseUrl|UsageTerms|"
            "NonFree|Restrictions|Categories"
        ),
        "iiextmetadatalanguage": "en",
    }
    try:
        with _json_client() as client:
            response = client.get(COMMONS_API, params=params)
    except httpx.HTTPError as exc:
        raise ImageSearchError("Wikimedia Commons could not be reached.", "wikimedia") from exc
    if response.status_code == 429:
        raise ImageSearchError(
            "Wikimedia Commons asked FrameFusion to slow down. Try again shortly.",
            "wikimedia",
            kind="rate_limited",
        )
    if response.status_code >= 400:
        raise ImageSearchError(
            f"Wikimedia Commons answered with HTTP {response.status_code}.", "wikimedia"
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise ImageSearchError(
            "Wikimedia Commons sent an unreadable response.", "wikimedia"
        ) from exc
    pages = (payload.get("query") or {}).get("pages") or []
    pages = sorted((p for p in pages if isinstance(p, dict)), key=lambda p: p.get("index", 0))
    candidates = []
    for page in pages:
        candidate = _commons_item(page)
        if candidate:
            candidates.append(candidate)
        if len(candidates) >= limit:
            break
    return candidates


# --- Openverse --------------------------------------------------------------------------


def _license_label(code: str, version: str | None) -> str:
    name = LICENSE_NAMES.get(code.lower(), code.upper() or "unknown")
    if code.lower() == "pdm":
        return f"{name} {version or '1.0'}"
    return f"{name} {version}".strip() if version else name


def _openverse_item(item: dict[str, Any]) -> ImageCandidate | None:
    url = item.get("url")
    identifier = item.get("id")
    if not url or not identifier:
        return None
    code = str(item.get("license") or "")
    label = _license_label(code, item.get("license_version"))
    filetype = str(item.get("filetype") or "").lower() or None
    return ImageCandidate(
        candidate_id=f"openverse:{identifier}",
        provider="openverse",
        title=clean_text(item.get("title") or "", 200),
        preview_url=item.get("thumbnail"),
        download_url=url,
        source_page_url=item.get("foreign_landing_url"),
        width=item.get("width"),
        height=item.get("height"),
        format="jpeg" if filetype in ("jpg", "jpeg") else filetype,
        creator=clean_text(item.get("creator") or "", 120) or None,
        creator_url=item.get("creator_url"),
        license=label,
        license_url=item.get("license_url"),
        attribution=clean_text(item.get("attribution") or "", 400) or None,
        rights_status="documented",
        usage_note=(
            f"{label} as reported by Openverse "
            f"({item.get('source') or item.get('provider') or 'source'}). "
            "Credit the creator and verify the licence on the source page."
        ),
        tags=[
            clean_text(tag.get("name", ""), 40)
            for tag in (item.get("tags") or [])[:8]
            if isinstance(tag, dict)
        ],
    )


def search_openverse(
    query: str, orientation: Orientation | None, limit: int
) -> list[ImageCandidate]:
    params: dict[str, Any] = {
        "q": query,
        "page_size": max(1, min(limit, 20)),
        "license": OPENVERSE_LICENSES,
        "extension": "jpg,png,webp",
        "mature": "false",
    }
    if orientation:
        params["aspect_ratio"] = OPENVERSE_ASPECT[orientation]
    try:
        with _json_client() as client:
            response = client.get(OPENVERSE_URL, params=params)
    except httpx.HTTPError as exc:
        raise ImageSearchError("Openverse could not be reached.", "openverse") from exc
    if response.status_code == 429:
        raise ImageSearchError(
            "Openverse rate limit reached (anonymous use allows about one search per second). "
            "Try again shortly.",
            "openverse",
            kind="rate_limited",
        )
    if response.status_code >= 400:
        raise ImageSearchError(f"Openverse answered with HTTP {response.status_code}.", "openverse")
    try:
        payload = response.json()
    except ValueError as exc:
        raise ImageSearchError("Openverse sent an unreadable response.", "openverse") from exc
    candidates = []
    for item in payload.get("results") or []:
        if not isinstance(item, dict) or item.get("mature"):
            continue
        candidate = _openverse_item(item)
        if candidate:
            candidates.append(candidate)
    return candidates


# --- Brave image search (discovery only) ------------------------------------------------


def search_brave(query: str, limit: int) -> list[ImageCandidate]:
    key = integrations.get_key("brave")
    if not key:
        raise ImageSearchError(
            "Brave image search isn't set up. Add a key in Settings.",
            "brave",
            kind="not_configured",
        )
    params: dict[str, str | int] = {
        "q": query[:400],
        "count": max(1, min(limit, 20)),
        "safesearch": "strict",
        "spellcheck": "0",
    }
    try:
        with _json_client({"X-Subscription-Token": key}) as client:
            response = client.get(BRAVE_URL, params=params)
    except httpx.HTTPError as exc:
        raise ImageSearchError("Brave Search could not be reached.", "brave") from exc
    if response.status_code == 429:
        raise ImageSearchError(
            "Brave Search rate limit or monthly credit reached.", "brave", kind="rate_limited"
        )
    if response.status_code in (401, 403):
        raise ImageSearchError(
            "Brave Search rejected the API key. Check it in Settings.",
            "brave",
            kind="invalid_credentials",
        )
    if response.status_code >= 400:
        raise ImageSearchError(f"Brave Search answered with HTTP {response.status_code}.", "brave")
    try:
        results = response.json().get("results") or []
    except ValueError as exc:
        raise ImageSearchError("Brave Search sent an unreadable response.", "brave") from exc
    candidates = []
    for item in results:
        if not isinstance(item, dict):
            continue
        properties = item.get("properties") or {}
        original = properties.get("url")
        if not original:
            continue
        digest = hashlib.sha256(str(original).encode()).hexdigest()[:16]
        candidates.append(
            ImageCandidate(
                candidate_id=f"brave:{digest}",
                provider="brave",
                title=clean_text(item.get("title") or "", 200),
                preview_url=(item.get("thumbnail") or {}).get("src") or original,
                download_url=str(original),
                source_page_url=item.get("url"),
                width=properties.get("width"),
                height=properties.get("height"),
                creator=clean_text(item.get("source") or "", 120) or None,
                rights_status="unknown",
                usage_note=BRAVE_NOTE,
            )
        )
    return candidates


# --- User-supplied ----------------------------------------------------------------------


def candidate_from_url(url: str, *, user_supplied: bool) -> ImageCandidate:
    checked = safe_fetch.check_url(url)
    digest = hashlib.sha256(checked.encode()).hexdigest()[:16]
    name = urlsplit(checked).path.rsplit("/", 1)[-1]
    return ImageCandidate(
        candidate_id=f"url:{digest}",
        provider="url",
        title=clean_text(name, 120),
        preview_url=checked,
        download_url=checked,
        source_page_url=None,
        user_supplied=user_supplied,
    )


def search_webpage(url: str, *, user_supplied: bool, limit: int) -> list[ImageCandidate]:
    return extract_candidates(url, user_supplied=user_supplied, limit=limit)


# --- Routing ----------------------------------------------------------------------------


def _interleave(groups: list[list[ImageCandidate]], limit: int) -> list[ImageCandidate]:
    merged: list[ImageCandidate] = []
    seen: set[str] = set()
    index = 0
    while len(merged) < limit and any(index < len(group) for group in groups):
        for group in groups:
            if index < len(group) and len(merged) < limit:
                candidate = group[index]
                if candidate.candidate_id not in seen:
                    seen.add(candidate.candidate_id)
                    merged.append(candidate)
        index += 1
    return merged


def plan_sources(brief: VisualBrief | None, *, configured_only: bool = True) -> list[str]:
    """Licensed sources to try for a brief, best first (Brave is never automatic)."""
    if brief is None:
        order = ["pexels", "pixabay", "wikimedia", "openverse"]
    elif brief.visual_type in ("diagram", "illustration"):
        order = ["wikimedia", "pixabay", "openverse"]
    elif brief.specificity == "exact":
        order = ["wikimedia", "openverse", "pexels"]
    elif brief.specificity == "representative":
        order = ["pexels", "wikimedia", "pixabay", "openverse"]
    else:
        order = ["pexels", "pixabay", "openverse"]
    return [source for source in order if not configured_only or available(source)]


def search_one(
    source: str,
    query: str,
    *,
    orientation: Orientation | None,
    limit: int,
    brief: VisualBrief | None = None,
    user_supplied: bool = False,
) -> list[ImageCandidate]:
    if source == "url":
        return [candidate_from_url(query, user_supplied=user_supplied)]
    if source == "webpage":
        return search_webpage(query, user_supplied=user_supplied, limit=limit)
    if source == "pexels":
        return search_pexels(query, orientation, limit)
    if source == "pixabay":
        visual = brief.visual_type if brief else "photograph"
        image_type = {"illustration": "illustration", "diagram": "vector"}.get(visual, "photo")
        return search_pixabay(query, orientation, limit, image_type=image_type)
    if source == "wikimedia":
        drawings = bool(brief and brief.visual_type in ("diagram", "illustration"))
        return search_wikimedia(query, limit, drawings=drawings)
    if source == "openverse":
        return search_openverse(query, orientation, limit)
    if source == "brave":
        return search_brave(query, limit)
    raise ValueError(f"Unknown image source: {source}")


def search(
    query: str,
    *,
    source: Source = "auto",
    orientation: Orientation | None = "portrait",
    limit: int = 8,
    user_supplied: bool = False,
    brief: VisualBrief | None = None,
) -> tuple[list[ImageCandidate], list[str]]:
    """Search one source, or the licensed sources suited to ``brief``; returns limitations too."""
    text = " ".join((query or "").split())
    if len(text) < 2:
        raise ValueError("Search for at least two characters.")
    limit = max(1, min(limit, 20))
    if source != "auto":
        return (
            search_one(
                source,
                text,
                orientation=orientation,
                limit=limit,
                brief=brief,
                user_supplied=user_supplied,
            ),
            [],
        )

    planned = plan_sources(brief)
    limitations = [
        f"{name.title()} isn't set up, so it was not searched."
        for name in plan_sources(brief, configured_only=False)
        if name not in planned
    ]
    groups: list[list[ImageCandidate]] = []
    for name in planned:
        try:
            groups.append(search_one(name, text, orientation=orientation, limit=limit, brief=brief))
        except ImageSearchError as exc:
            limitations.append(str(exc))
    if not groups:
        raise ImageSearchError(" ".join(limitations) or "No image source is available.", "auto")
    return _interleave(groups, limit), limitations
