"""Extract image candidates from a public web page.

The page is fetched through ``safe_fetch`` (no cookies, no auth) and parsed with
the standard library HTML parser. Everything taken from the page is untrusted:
text is flattened and truncated, and only http(s) image URLs are kept. The page
is never executed and nothing behind a login or paywall is attempted.
"""

from __future__ import annotations

import hashlib
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from engine.services.images import safe_fetch
from engine.services.images.candidates import ImageCandidate, clean_text

MAX_PAGE_BYTES = 3 * 1024 * 1024
IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")
SKIP_HINTS = ("logo", "icon", "sprite", "avatar", "favicon", "pixel", "spacer", "badge", "emoji")


class _ImageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: list[tuple[str, str]] = []
        self.images: list[dict[str, str]] = []
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): (value or "") for key, value in attrs}
        if tag == "meta":
            key = (values.get("property") or values.get("name") or "").lower()
            if key in (
                "og:image",
                "og:image:url",
                "og:image:secure_url",
                "twitter:image",
            ) and values.get("content"):
                self.meta.append((key, values["content"]))
            if key == "og:title" and values.get("content") and not self.title:
                self.title = values["content"]
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

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title and len(self.title) < 200:
            self.title += data


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


def extract_candidates(
    page_url: str, *, user_supplied: bool, limit: int = 12
) -> list[ImageCandidate]:
    fetched = safe_fetch.fetch_bytes(
        page_url, max_bytes=MAX_PAGE_BYTES, accept=("text/html", "application/xhtml")
    )
    parser = _ImageParser()
    parser.feed(fetched.data.decode("utf-8", errors="replace"))
    page_title = clean_text(parser.title, 160)

    found: list[tuple[str, str, int | None, int | None]] = []
    for _key, content in parser.meta:
        found.append((urljoin(fetched.url, content), page_title, None, None))
    for image in parser.images:
        found.append(
            (
                urljoin(fetched.url, image["src"]),
                image["alt"] or page_title,
                _int(image["width"]),
                _int(image["height"]),
            )
        )

    seen: set[str] = set()
    candidates: list[ImageCandidate] = []
    for url, title, width, height in found:
        if url in seen or not _usable(url):
            continue
        if width and height and min(width, height) < 200:
            continue
        seen.add(url)
        digest = hashlib.sha256(url.encode()).hexdigest()[:16]
        candidates.append(
            ImageCandidate(
                candidate_id=f"webpage:{digest}",
                provider="webpage",
                title=clean_text(title, 160),
                preview_url=url,
                download_url=url,
                source_page_url=fetched.url,
                width=width,
                height=height,
                creator=urlsplit(fetched.url).hostname,
                user_supplied=user_supplied,
            )
        )
        if len(candidates) >= limit:
            break
    return candidates
