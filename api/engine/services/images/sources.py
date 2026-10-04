"""Image search adapters.

* Pexels (``/v1/search``) needs the Pexels key from Settings; every photo is
  under the Pexels License (https://www.pexels.com/license/).
* Openverse (``GET https://api.openverse.org/v1/images/``) needs no key. It
  indexes openly licensed and public-domain images (Wikimedia Commons, Flickr,
  museums and more) and reports each image's licence. Anonymous use is rate
  limited (about one request per second, at most 20 results per page), so a 429
  is reported as a limitation rather than retried in a loop.
* A direct image URL or a public web page the user supplied. Their reuse
  rights are unknown and they are marked as such.

FrameFusion never claims reuse rights; it reports the licence the source gives.
"""

from __future__ import annotations

import hashlib
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx

from engine import integrations
from engine.services import pexels_client
from engine.services.images import safe_fetch
from engine.services.images.candidates import ImageCandidate, clean_text
from engine.services.images.webpage import extract_candidates

Orientation = Literal["portrait", "landscape", "square"]
Source = Literal["auto", "pexels", "openverse", "url", "webpage"]

OPENVERSE_URL = "https://api.openverse.org/v1/images/"
OPENVERSE_LICENSES = "by,by-sa,cc0,pdm"
PEXELS_LICENSE_URL = "https://www.pexels.com/license/"
PEXELS_NOTE = (
    "Pexels License: free to use and modify, attribution appreciated. It does not cover "
    "identifiable people or brands in endorsements or selling unaltered copies; check the licence."
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


class ImageSearchError(Exception):
    def __init__(self, message: str, source: str, *, kind: str = "search_failed") -> None:
        super().__init__(message)
        self.source = source
        self.kind = kind


def pexels_available() -> bool:
    return integrations.is_configured("pexels")


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
        with httpx.Client(
            transport=safe_fetch.TRANSPORT,
            timeout=httpx.Timeout(20.0, connect=8.0),
            trust_env=False,
            headers={"User-Agent": safe_fetch.USER_AGENT, "Accept": "application/json"},
        ) as client:
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


def _interleave(groups: list[list[ImageCandidate]], limit: int) -> list[ImageCandidate]:
    merged: list[ImageCandidate] = []
    index = 0
    while len(merged) < limit and any(index < len(group) for group in groups):
        for group in groups:
            if index < len(group) and len(merged) < limit:
                merged.append(group[index])
        index += 1
    return merged


def search(
    query: str,
    *,
    source: Source = "auto",
    orientation: Orientation | None = "portrait",
    limit: int = 8,
    user_supplied: bool = False,
) -> tuple[list[ImageCandidate], list[str]]:
    """Search one or all sources; returns candidates and human-readable limitations."""
    text = " ".join((query or "").split())
    if len(text) < 2:
        raise ValueError("Search for at least two characters.")
    limit = max(1, min(limit, 20))
    if source == "url":
        return [candidate_from_url(text, user_supplied=user_supplied)], []
    if source == "webpage":
        return search_webpage(text, user_supplied=user_supplied, limit=limit), []
    if source == "pexels":
        return search_pexels(text, orientation, limit), []
    if source == "openverse":
        return search_openverse(text, orientation, limit), []

    groups: list[list[ImageCandidate]] = []
    limitations: list[str] = []
    if pexels_available():
        try:
            groups.append(search_pexels(text, orientation, limit))
        except ImageSearchError as exc:
            limitations.append(str(exc))
    else:
        limitations.append("Pexels isn't set up, so only Openverse was searched.")
    try:
        groups.append(search_openverse(text, orientation, limit))
    except ImageSearchError as exc:
        limitations.append(str(exc))
    if not groups:
        raise ImageSearchError(" ".join(limitations) or "No image source is available.", "auto")
    return _interleave(groups, limit), limitations
