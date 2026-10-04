"""Links you paste after searching Google Images (or any site) in your own browser.

FrameFusion never requests Google pages: Google's terms forbid automated access
to paths its robots.txt disallows, which include ``/search`` and ``/imgres``.
A Google result link is read locally instead. ``/imgres`` links carry the image
(``imgurl``) and the publisher page (``imgrefurl``) in their query string, and
``/url`` redirect links carry their destination. Results pages, Google's
thumbnails and embedded ``data:`` previews are refused with instructions,
because they are not the original image.

The publisher page and the image are then fetched through ``safe_fetch`` like
any other link you supply. Rights stay ``unknown`` until you review them.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from engine.services.images import safe_fetch
from engine.services.images.candidates import (
    MAX_IMAGE_BYTES,
    ImageCandidate,
    InvalidImage,
    clean_text,
    validate_image,
)
from engine.services.images.webpage import (
    PAGE_ACCEPT,
    Page,
    PageImage,
    candidate_for,
    page_candidates,
    parse_page,
    read_page,
    same_image,
    usage_note,
)

GOOGLE_IMAGES = "google_images"
_GOOGLE_HOST = re.compile(r"(^|\.)google\.(com|[a-z]{2}|co\.[a-z]{2}|com\.[a-z]{2})$")
_GOOGLE_THUMBNAIL = re.compile(r"^(encrypted-)?tbn\d*\.gstatic\.com$")

RESULTS_PAGE_HELP = (
    "That's a Google results page, and FrameFusion doesn't read Google itself. Click a result, "
    "open the website it comes from, then copy that page's address, or right-click the full-size "
    "image there and copy the image address."
)
THUMBNAIL_HELP = (
    "That's Google's preview thumbnail, not the original image, and it is too small for a video. "
    "Open the result's website and copy the page address or the full-size image address there."
)


class PastedLinkError(Exception):
    def __init__(self, message: str, kind: str = "bad_link") -> None:
        super().__init__(message)
        self.kind = kind


@dataclass
class PastedLink:
    image_url: str | None
    page_url: str | None
    via_google: bool
    width: int | None = None
    height: int | None = None


def _host(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").rstrip(".").lower()
    except ValueError:
        return ""


def is_google_host(host: str) -> bool:
    return bool(_GOOGLE_HOST.search(host))


def is_google_thumbnail(host: str) -> bool:
    return bool(_GOOGLE_THUMBNAIL.match(host))


def _first(query: dict[str, list[str]], *keys: str) -> str | None:
    for key in keys:
        values = query.get(key)
        if values and values[0].strip():
            return values[0].strip()
    return None


def _size(value: str | None) -> int | None:
    return int(value) if value and value.isdigit() and 0 < int(value) < 20000 else None


def parse_link(text: str, *, _depth: int = 0) -> PastedLink:
    """Work out the image and page a pasted link points to, without fetching anything."""
    link = " ".join((text or "").split())
    if not link:
        raise PastedLinkError("Paste an image or page link.")
    if link.lower().startswith("data:"):
        raise PastedLinkError(THUMBNAIL_HELP, "preview_only")
    if "://" not in link:
        link = "https://" + link
    host = _host(link)
    if not host:
        raise PastedLinkError("That doesn't look like a web address.")
    if is_google_thumbnail(host):
        raise PastedLinkError(THUMBNAIL_HELP, "preview_only")
    if not is_google_host(host):
        return PastedLink(image_url=None, page_url=link, via_google=False)

    parts = urlsplit(link)
    query = parse_qs(parts.query)
    path = parts.path.rstrip("/")
    if path == "/imgres":
        image = _first(query, "imgurl")
        page = _first(query, "imgrefurl")
        if not image and not page:
            raise PastedLinkError(RESULTS_PAGE_HELP, "google_page")
        for target in (image, page):
            if target and (is_google_host(_host(target)) or is_google_thumbnail(_host(target))):
                raise PastedLinkError(THUMBNAIL_HELP, "preview_only")
        return PastedLink(
            image_url=image,
            page_url=page,
            via_google=True,
            width=_size(_first(query, "w")),
            height=_size(_first(query, "h")),
        )
    if path == "/url" and _depth == 0:
        target = _first(query, "q", "url")
        if target and target.startswith(("http://", "https://")):
            inner = parse_link(target, _depth=1)
            if inner.via_google or is_google_host(_host(target)):
                raise PastedLinkError(RESULTS_PAGE_HELP, "google_page")
            return PastedLink(image_url=None, page_url=inner.page_url, via_google=True)
    raise PastedLinkError(RESULTS_PAGE_HELP, "google_page")


def _direct_candidate(
    url: str, *, data: bytes, via_google: bool, page: Page | None
) -> ImageCandidate:
    try:
        image = validate_image(data)
    except InvalidImage as exc:
        raise PastedLinkError(str(exc), "invalid_image") from exc
    digest = hashlib.sha256(url.encode()).hexdigest()[:16]
    name = urlsplit(url).path.rsplit("/", 1)[-1]
    return ImageCandidate(
        candidate_id=f"url:{digest}",
        provider="url",
        title=clean_text(name, 120),
        preview_url=url,
        download_url=url,
        width=image.width,
        height=image.height,
        format=image.format,
        rights_status="unknown",
        usage_note=usage_note(page, None, via_google=via_google),
        user_supplied=True,
        discovered_via=GOOGLE_IMAGES if via_google else None,
    )


def resolve(text: str, *, limit: int = 8) -> tuple[list[ImageCandidate], list[str]]:
    """Candidates for a pasted link (the image you picked first) and notes for the user."""
    link = parse_link(text)
    via = GOOGLE_IMAGES if link.via_google else None
    notes: list[str] = []

    if link.image_url:
        image_url = safe_fetch.check_url(link.image_url)
        page: Page | None = None
        if link.page_url:
            try:
                page = read_page(link.page_url)
            except safe_fetch.FetchError as exc:
                notes.append(
                    f"Couldn't open the publisher's page ({exc}) so its licence and credit are "
                    "unknown."
                )
        if page is None:
            candidate = ImageCandidate(
                candidate_id=f"url:{hashlib.sha256(image_url.encode()).hexdigest()[:16]}",
                provider="url",
                title=clean_text(urlsplit(image_url).path.rsplit("/", 1)[-1], 120),
                preview_url=image_url,
                download_url=image_url,
                source_page_url=link.page_url,
                width=link.width,
                height=link.height,
                rights_status="unknown",
                usage_note=usage_note(None, None, via_google=link.via_google),
                user_supplied=True,
                discovered_via=via,
                publisher=_host(link.page_url or "") or None,
            )
            return [candidate], notes
        match = next((item for item in page.images if same_image(item.url, image_url)), None)
        if match is None:
            notes.append(
                "The image wasn't found on the publisher's page as it is now; it may have moved "
                "or been removed. Check the source before using it."
            )
        picked = PageImage(
            url=image_url,
            title=(match.title if match else "") or page.title,
            width=link.width or (match.width if match else None),
            height=link.height or (match.height if match else None),
        )
        first = candidate_for(
            picked,
            page,
            user_supplied=True,
            discovered_via=via,
            found_on_page=match is not None,
        )
        others = [
            candidate
            for candidate in page_candidates(
                page, user_supplied=True, limit=limit, discovered_via=via
            )
            if not same_image(candidate.download_url, image_url)
        ]
        return [first, *others][:limit], notes

    assert link.page_url is not None
    fetched = safe_fetch.fetch_bytes(
        link.page_url, max_bytes=MAX_IMAGE_BYTES, accept=("image/", *PAGE_ACCEPT)
    )
    if fetched.content_type.startswith("image/"):
        notes.append(
            "This is a direct image link. Paste the page it appears on instead to record the "
            "publisher's licence and credit."
        )
        return [
            _direct_candidate(fetched.url, data=fetched.data, via_google=link.via_google, page=None)
        ], notes
    if len(fetched.data) > 3 * 1024 * 1024:
        raise PastedLinkError("That page is too large to read.", "too_large")
    page = parse_page(fetched)
    found = page_candidates(page, user_supplied=True, limit=limit, discovered_via=via)
    if not found:
        notes.append(
            "No usable images were found on that page (logos, icons and tiny images are skipped, "
            "and images loaded by scripts can't be seen). Copy the image address instead."
        )
    return found, notes
