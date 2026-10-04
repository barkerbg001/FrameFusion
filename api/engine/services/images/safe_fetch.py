"""Outbound HTTP for user- and model-chosen URLs.

Every URL is treated as hostile: only http(s) on standard ports, no embedded
credentials, every hop (including redirects) must resolve to public addresses,
the connected peer is re-checked after connecting, bodies are streamed with a
hard size cap, and retries are bounded. No cookies or auth headers are sent, so
nothing behind a login or paywall can be reached.
"""

from __future__ import annotations

import ipaddress
import socket
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx

from engine.runtime import check_cancelled

USER_AGENT = "FrameFusion/1.0 (local video studio; image research)"
ALLOWED_SCHEMES = {"http", "https"}
ALLOWED_PORTS = {None, 80, 443}
MAX_REDIRECTS = 4
MAX_ATTEMPTS = 3
RETRY_STATUSES = {429, 500, 502, 503, 504}
TIMEOUT = httpx.Timeout(20.0, connect=8.0)

# Tests replace these to avoid real DNS and sockets.
TRANSPORT: httpx.BaseTransport | None = None
sleep: Callable[[float], None] = time.sleep


def _system_resolve(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return sorted({str(info[4][0]) for info in infos})


resolve_host: Callable[[str], list[str]] = _system_resolve


class FetchError(Exception):
    """A download that was refused or failed; ``kind`` is safe to show."""

    def __init__(self, message: str, kind: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.kind = kind
        self.retryable = retryable


@dataclass
class Fetched:
    url: str
    status: int
    content_type: str
    data: bytes


def _is_public(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def check_url(url: str) -> str:
    """Validate scheme, port, credentials and DNS; return the normalised URL."""
    text = (url or "").strip()
    if not text or len(text) > 2048:
        raise FetchError("The URL is empty or too long.", "blocked_url")
    try:
        parts = urlsplit(text)
        port = parts.port
    except ValueError as exc:
        raise FetchError("The URL is not valid.", "blocked_url") from exc
    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise FetchError("Only http and https URLs can be fetched.", "blocked_url")
    if parts.username or parts.password:
        raise FetchError("URLs with embedded credentials are not allowed.", "blocked_url")
    if port not in ALLOWED_PORTS:
        raise FetchError("Only the standard web ports (80 and 443) are allowed.", "blocked_url")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host or host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise FetchError("That host is not a public website.", "blocked_url")
    try:
        addresses = [host] if _looks_like_ip(host) else resolve_host(host)
    except OSError as exc:
        raise FetchError(f"Could not resolve {host}.", "network", retryable=True) from exc
    if not addresses or not all(_is_public(address) for address in addresses):
        raise FetchError(
            "That address is private or reserved and cannot be fetched.", "blocked_url"
        )
    return text


def _looks_like_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return True


def _check_peer(response: httpx.Response) -> None:
    stream = response.extensions.get("network_stream")
    if stream is None:
        return
    peer = stream.get_extra_info("server_addr")
    if peer and not _is_public(str(peer[0])):
        raise FetchError("The server resolved to a private address.", "blocked_url")


def _client() -> httpx.Client:
    return httpx.Client(
        transport=TRANSPORT,
        follow_redirects=False,
        trust_env=False,
        timeout=TIMEOUT,
        headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
    )


def _status_error(status: int) -> FetchError:
    if status in (401, 402, 403, 407):
        return FetchError(
            "The site requires a sign-in or subscription. FrameFusion does not bypass logins "
            "or paywalls.",
            "access_denied",
        )
    if status in (404, 410):
        return FetchError("The file no longer exists at that address.", "not_found")
    return FetchError(
        f"The site answered with HTTP {status}.", "http_error", retryable=status in RETRY_STATUSES
    )


@contextmanager
def _open(url: str, accept: tuple[str, ...]) -> Iterator[httpx.Response]:
    current = check_url(url)
    with _client() as client:
        for _hop in range(MAX_REDIRECTS + 1):
            with client.stream("GET", current) as response:
                _check_peer(response)
                if response.is_redirect:
                    location = response.headers.get("location", "")
                    if not location:
                        raise FetchError("A redirect had no destination.", "http_error")
                    current = check_url(urljoin(current, location))
                    continue
                if response.status_code >= 400:
                    raise _status_error(response.status_code)
                content_type = (
                    response.headers.get("content-type", "").split(";")[0].strip().lower()
                )
                if accept and not content_type.startswith(accept):
                    raise FetchError(
                        f"Expected {', '.join(accept)} but the server sent "
                        f"{content_type or 'an unknown type'}.",
                        "bad_type",
                    )
                yield response
                return
    raise FetchError("Too many redirects.", "http_error")


def _declared_length(response: httpx.Response, max_bytes: int) -> None:
    length = response.headers.get("content-length", "")
    if length.isdigit() and int(length) > max_bytes:
        raise FetchError(f"The file is larger than {max_bytes // (1024 * 1024)} MB.", "too_large")


def _with_retries[T](action: Callable[[], T]) -> T:
    for attempt in range(1, MAX_ATTEMPTS + 1):
        check_cancelled()
        try:
            return action()
        except FetchError as exc:
            if not exc.retryable or attempt == MAX_ATTEMPTS:
                raise
        except httpx.TimeoutException as exc:
            if attempt == MAX_ATTEMPTS:
                raise FetchError(
                    "The site took too long to respond.", "timeout", retryable=True
                ) from exc
        except httpx.HTTPError as exc:
            if attempt == MAX_ATTEMPTS:
                raise FetchError(
                    f"Network error: {type(exc).__name__}.", "network", retryable=True
                ) from exc
        sleep(0.5 * attempt)
    raise FetchError("The download failed.", "network")  # pragma: no cover


def fetch_bytes(url: str, *, max_bytes: int, accept: tuple[str, ...] = ()) -> Fetched:
    """Download a small body into memory, enforcing every safety check."""

    def attempt() -> Fetched:
        with _open(url, accept) as response:
            _declared_length(response, max_bytes)
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_bytes(64 * 1024):
                total += len(chunk)
                if total > max_bytes:
                    raise FetchError(
                        f"The file is larger than {max_bytes // (1024 * 1024)} MB.", "too_large"
                    )
                chunks.append(chunk)
            return Fetched(
                url=str(response.url),
                status=response.status_code,
                content_type=response.headers.get("content-type", "").split(";")[0].strip().lower(),
                data=b"".join(chunks),
            )

    return _with_retries(attempt)


def fetch_to_file(
    url: str, destination: Path, *, max_bytes: int, accept: tuple[str, ...] = ()
) -> Path:
    """Stream a large body to ``destination``; partial files are always removed."""
    partial = destination.with_name(destination.name + ".part")

    def attempt() -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            with _open(url, accept) as response:
                _declared_length(response, max_bytes)
                total = 0
                with partial.open("wb") as handle:
                    for chunk in response.iter_bytes(256 * 1024):
                        total += len(chunk)
                        if total > max_bytes:
                            raise FetchError(
                                f"The file is larger than {max_bytes // (1024 * 1024)} MB.",
                                "too_large",
                            )
                        handle.write(chunk)
                if total == 0:
                    raise FetchError("The server sent an empty file.", "invalid_file")
            partial.replace(destination)
            return destination
        finally:
            partial.unlink(missing_ok=True)

    return _with_retries(attempt)
