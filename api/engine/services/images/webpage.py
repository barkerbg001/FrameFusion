"""Extract image candidates and declared rights from a public web page.

The page is fetched through ``safe_fetch`` (no cookies, no auth) and parsed with
the standard library HTML parser. Everything taken from the page is untrusted:
text is flattened and truncated, and only http(s) image URLs are kept. The page
is never executed and nothing behind a login or paywall is attempted.

Rights a publisher declares (schema.org ``ImageObject`` licence and credit, a
``rel="license"`` link, author and copyright meta tags) are recorded so you can
review them, but they are never verified: candidates from a page always keep
``rights_status="unknown"``.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any
from urllib.parse import unquote, urljoin, urlsplit

from engine.services.images import safe_fetch
from engine.services.images.candidates import ImageCandidate, clean_text

MAX_PAGE_BYTES = 3 * 1024 * 1024
MAX_JSON_LD_BYTES = 256 * 1024
IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")
SKIP_HINTS = ("logo", "icon", "sprite", "avatar", "favicon", "pixel", "spacer", "badge", "emoji")
PAGE_ACCEPT = ("text/html", "application/xhtml")

_META_RIGHTS = {
    "author": "author",
    "article:author": "author",
    "copyright": "copyright",
    "dcterms.rights": "copyright",
    "dc.rights": "copyright",
    "og:site_name": "site_name",
}
_CC = re.compile(
    r"creativecommons\.org/(licenses|publicdomain)/([a-z-]+)(?:/(\d(?:\.\d)?))?", re.IGNORECASE
)
_PUBLIC_DOMAIN = re.compile(r"public[ _-]?domain", re.IGNORECASE)


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: list[tuple[str, str]] = []
        self.images: list[dict[str, str]] = []
        self.title = ""
        self.rights_meta: dict[str, str] = {}
        self.license_links: list[str] = []
        self.json_ld: list[str] = []
        self._in_title = False
        self._in_json_ld = False
        self._json_ld_bytes = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): (value or "") for key, value in attrs}
        if tag == "meta":
            key = (values.get("property") or values.get("name") or "").lower()
            content = values.get("content", "")
            if not content:
                return
            if key in ("og:image", "og:image:url", "og:image:secure_url", "twitter:image"):
                self.meta.append((key, content))
            elif key == "og:title" and not self.title:
                self.title = content
            elif key in _META_RIGHTS:
                self.rights_meta.setdefault(_META_RIGHTS[key], content)
        elif tag in ("link", "a"):
            rel = values.get("rel", "").lower().split()
            if "license" in rel and values.get("href"):
                self.license_links.append(values["href"])
        elif tag == "img":
            src = values.get("src") or values.get("data-src") or ""
            srcset = values.get("srcset") or ""
            if srcset:
                best = srcset.split(",")[-1].strip().split(" ")[0]
                src = best or src
            if src:
                self.images.append(
                    {
                        "src": src,
                        "alt": values.get("alt", ""),
                        "width": values.get("width", ""),
                        "height": values.get("height", ""),
                    }
                )
        elif tag == "title":
            self._in_title = True
        elif tag == "script" and values.get("type", "").lower() == "application/ld+json":
            self._in_json_ld = True
            self.json_ld.append("")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag == "script":
            self._in_json_ld = False

    def handle_data(self, data: str) -> None:
        if self._in_title and len(self.title) < 200:
            self.title += data
        elif self._in_json_ld and self._json_ld_bytes < MAX_JSON_LD_BYTES:
            self._json_ld_bytes += len(data)
            self.json_ld[-1] += data


@dataclass
class PageImage:
    url: str
    title: str
    width: int | None
    height: int | None


@dataclass
class PageRights:
    """What the publisher states about an image. Unverified; shown for your review."""

    license: str | None = None
    license_url: str | None = None
    creator: str | None = None
    credit: str | None = None
    copyright: str | None = None
    acquire_license_page: str | None = None

    @property
    def declared(self) -> bool:
        return bool(self.license or self.license_url or self.credit or self.copyright)


@dataclass
class Page:
    url: str
    title: str
    publisher: str
    images: list[PageImage] = field(default_factory=list)
    parser: _PageParser | None = None

    def rights_for(self, image_url: str | None = None) -> PageRights:
        return _rights(self, image_url)


def _int(value: str) -> int | None:
    return int(value) if value.isdigit() and 0 < int(value) < 20000 else None


def _usable(url: str) -> bool:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return False
    path = parts.path.lower()
    if path.endswith((".svg", ".gif", ".ico")):
        return False
    name = path.rsplit("/", 1)[-1]
    return not any(hint in name for hint in SKIP_HINTS)


def _site(host: str) -> str:
    return ".".join(host.lower().split(".")[-2:])


def _file_name(path: str) -> str:
    name = unquote(path.rsplit("/", 1)[-1]).lower()
    return name if name.endswith(IMAGE_SUFFIXES) and len(name) >= 8 else ""


def same_image(first: str, second: str) -> bool:
    """Same file, ignoring scheme, host case, query strings (CDN sizing) and fragments.

    A resized copy on the same site counts when the original's file name is a directory in
    the copy's path (``/thumb/a/a8/Name.jpg/960px-Name.jpg``). Two files that merely share a
    name in different folders do not.
    """
    a, b = urlsplit(first), urlsplit(second)
    host_a, host_b = (a.hostname or "").lower(), (b.hostname or "").lower()
    if host_a == host_b and a.path == b.path:
        return True
    if not host_a or _site(host_a) != _site(host_b):
        return False
    folders_a = {unquote(part).lower() for part in a.path.split("/")[:-1]}
    folders_b = {unquote(part).lower() for part in b.path.split("/")[:-1]}
    name_a, name_b = _file_name(a.path), _file_name(b.path)
    return bool((name_a and name_a in folders_b) or (name_b and name_b in folders_a))


def parse_page(fetched: safe_fetch.Fetched) -> Page:
    parser = _PageParser()
    parser.feed(fetched.data.decode("utf-8", errors="replace"))
    host = urlsplit(fetched.url).hostname or ""
    title = clean_text(parser.title, 160)
    # The original a page declares in its structured data comes first, then share images,
    # then the images in the page body; resized copies of one file are kept once.
    found: list[PageImage] = []
    for declared in _ld_image_objects(parser):
        content = _text(declared.get("contentUrl")) or _text(declared.get("url"))
        if content:
            name = _text(declared.get("name")) or _text(declared.get("caption")) or ""
            found.append(
                PageImage(
                    urljoin(fetched.url, content),
                    clean_text(name, 160) or title,
                    _int(str(declared.get("width") or "")),
                    _int(str(declared.get("height") or "")),
                )
            )
    for _key, content in parser.meta:
        found.append(PageImage(urljoin(fetched.url, content), title, None, None))
    for image in parser.images:
        found.append(
            PageImage(
                urljoin(fetched.url, image["src"]),
                image["alt"] or title,
                _int(image["width"]),
                _int(image["height"]),
            )
        )
    images: list[PageImage] = []
    for item in found:
        if not _usable(item.url):
            continue
        if item.width and item.height and min(item.width, item.height) < 200:
            continue
        kept = next((image for image in images if same_image(item.url, image.url)), None)
        if kept is None:
            images.append(item)
            continue
        if kept.title == title and item.title:
            kept.title = item.title
    publisher = clean_text(parser.rights_meta.get("site_name") or host, 120)
    return Page(url=fetched.url, title=title, publisher=publisher, images=images, parser=parser)


def read_page(page_url: str) -> Page:
    fetched = safe_fetch.fetch_bytes(page_url, max_bytes=MAX_PAGE_BYTES, accept=PAGE_ACCEPT)
    return parse_page(fetched)


# --- Declared rights ----------------------------------------------------------------------


def license_label(url: str) -> str | None:
    match = _CC.search(url or "")
    if not match:
        return "Public domain" if _PUBLIC_DOMAIN.search(unquote(url or "")) else None
    kind, code, version = match.group(1).lower(), match.group(2).lower(), match.group(3)
    if kind == "publicdomain":
        return "CC0" if code == "zero" else "Public Domain Mark"
    return f"CC {code.upper()} {version or ''}".strip()


def _text(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("name", "url", "@id"):
            if isinstance(value.get(key), str):
                return str(value[key])
    if isinstance(value, list) and value:
        return _text(value[0])
    return None


def _ld_objects(data: Any, depth: int = 0) -> Iterator[dict[str, Any]]:
    if depth > 6:
        return
    if isinstance(data, list):
        for item in data[:50]:
            yield from _ld_objects(item, depth + 1)
    elif isinstance(data, dict):
        yield data
        for key in ("@graph", "image", "primaryImageOfPage", "associatedMedia"):
            if key in data:
                yield from _ld_objects(data[key], depth + 1)


def _is_type(item: dict[str, Any], name: str) -> bool:
    kind = item.get("@type")
    kinds = kind if isinstance(kind, list) else [kind]
    return name in [str(k) for k in kinds]


def _ld_image_objects(parser: _PageParser | None) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    for block in parser.json_ld if parser else []:
        try:
            objects.extend(_ld_objects(json.loads(block)))
        except (ValueError, RecursionError):
            continue
    return [item for item in objects if _is_type(item, "ImageObject")]


def _ld_rights(page: Page, image_url: str | None) -> dict[str, Any] | None:
    images = _ld_image_objects(page.parser)
    if image_url:
        for item in images:
            for key in ("contentUrl", "url"):
                value = _text(item.get(key))
                if value and same_image(urljoin(page.url, value), image_url):
                    return item
    for item in images:
        if item.get("license") or item.get("creditText") or item.get("copyrightNotice"):
            # Only trust a page-wide ImageObject when the image we want isn't identified.
            return item if not image_url or len(images) == 1 else None
    return None


def _rights(page: Page, image_url: str | None) -> PageRights:
    rights = PageRights()
    parser = page.parser
    item = _ld_rights(page, image_url)
    if item is not None:
        license_value = _text(item.get("license"))
        if license_value and license_value.startswith(("http://", "https://", "/")):
            rights.license_url = urljoin(page.url, license_value)
        elif license_value:
            rights.license = clean_text(license_value, 60)
        rights.creator = clean_text(_text(item.get("creator")) or "", 120) or None
        rights.credit = clean_text(_text(item.get("creditText")) or "", 200) or None
        rights.copyright = clean_text(_text(item.get("copyrightNotice")) or "", 200) or None
        acquire = _text(item.get("acquireLicensePage"))
        if acquire:
            rights.acquire_license_page = urljoin(page.url, acquire)
    if parser is not None:
        if not rights.license_url and parser.license_links:
            rights.license_url = urljoin(page.url, parser.license_links[0])
        if not rights.creator and parser.rights_meta.get("author"):
            rights.creator = clean_text(parser.rights_meta["author"], 120)
        if not rights.copyright and parser.rights_meta.get("copyright"):
            rights.copyright = clean_text(parser.rights_meta["copyright"], 200)
    if rights.license_url and not rights.license:
        rights.license = license_label(rights.license_url)
    return rights


def usage_note(page: Page | None, rights: PageRights | None, *, via_google: bool) -> str:
    where = f" on {page.publisher}" if page and page.publisher else ""
    found = f"Found by you via Google Images{where}. " if via_google else f"Found{where}. "
    google = "Google doesn't grant reuse rights. " if via_google else ""
    if rights and rights.declared:
        stated = rights.license or ("a licence page" if rights.license_url else "")
        parts = [f"The page states {stated}" if stated else ""]
        if rights.copyright:
            parts.append(rights.copyright)
        declared = "; ".join(part for part in parts if part)
        declared = (declared + ". ") if declared else ""
        return (
            f"{found}{google}{declared}This is the publisher's statement, not verified by "
            "FrameFusion. Check it before publishing."
        )[:400]
    return (
        f"{found}{google}No licence information was found. Only use it if you own it or have "
        "permission."
    )[:400]


# --- Candidates ---------------------------------------------------------------------------


def candidate_for(
    image: PageImage,
    page: Page,
    *,
    user_supplied: bool,
    discovered_via: str | None = None,
    found_on_page: bool | None = None,
) -> ImageCandidate:
    rights = page.rights_for(image.url)
    via_google = discovered_via == "google_images"
    digest = hashlib.sha256(image.url.encode()).hexdigest()[:16]
    attribution = rights.credit or (
        f"{rights.creator} via {page.publisher}" if rights.creator else None
    )
    license_text = "unknown"
    if rights.license:
        license_text = f"{rights.license} (stated by publisher)"
    elif rights.license_url:
        license_text = "Stated by publisher"
    return ImageCandidate(
        candidate_id=f"webpage:{digest}",
        provider="webpage",
        title=clean_text(image.title, 160),
        preview_url=image.url,
        download_url=image.url,
        source_page_url=page.url,
        width=image.width,
        height=image.height,
        creator=rights.creator or page.publisher or None,
        license=license_text,
        license_url=rights.license_url or rights.acquire_license_page,
        attribution=clean_text(attribution or "", 300) or None,
        rights_status="unknown",
        usage_note=usage_note(page, rights, via_google=via_google),
        user_supplied=user_supplied,
        discovered_via=discovered_via,
        publisher=page.publisher or None,
        found_on_page=found_on_page,
    )


def page_candidates(
    page: Page, *, user_supplied: bool, limit: int, discovered_via: str | None = None
) -> list[ImageCandidate]:
    return [
        candidate_for(
            image,
            page,
            user_supplied=user_supplied,
            discovered_via=discovered_via,
            found_on_page=True,
        )
        for image in page.images[:limit]
    ]


def extract_candidates(
    page_url: str, *, user_supplied: bool, limit: int = 12
) -> list[ImageCandidate]:
    return page_candidates(read_page(page_url), user_supplied=user_supplied, limit=limit)
