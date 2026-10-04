"""File responses with HTTP Range support so browsers can seek in media."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import quote

from django.http import FileResponse, HttpRequest, HttpResponse, StreamingHttpResponse

_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")
CHUNK = 64 * 1024


def _iter_range(path: Path, start: int, length: int) -> Iterator[bytes]:
    with path.open("rb") as handle:
        handle.seek(start)
        remaining = length
        while remaining > 0:
            chunk = handle.read(min(CHUNK, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def _disposition(download_name: str, as_attachment: bool) -> str:
    kind = "attachment" if as_attachment else "inline"
    ascii_name = download_name.encode("ascii", "ignore").decode() or "download"
    ascii_name = ascii_name.replace('"', "")
    return f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(download_name)}"


def serve_file(
    request: HttpRequest,
    path: Path,
    *,
    content_type: str,
    download_name: str,
    as_attachment: bool = False,
) -> HttpResponse | StreamingHttpResponse | FileResponse:
    size = path.stat().st_size
    header = request.headers.get("Range", "")
    match = _RANGE.match(header.strip()) if header else None
    if match and (match.group(1) or match.group(2)):
        start_text, end_text = match.groups()
        if start_text:
            start = int(start_text)
            end = int(end_text) if end_text else size - 1
        else:
            suffix = int(end_text)
            start = max(0, size - suffix)
            end = size - 1
        end = min(end, size - 1)
        if start > end or start >= size:
            response = HttpResponse(status=416)
            response["Content-Range"] = f"bytes */{size}"
            return response
        length = end - start + 1
        partial = StreamingHttpResponse(
            _iter_range(path, start, length), status=206, content_type=content_type
        )
        partial["Content-Length"] = str(length)
        partial["Content-Range"] = f"bytes {start}-{end}/{size}"
        partial["Accept-Ranges"] = "bytes"
        partial["Content-Disposition"] = _disposition(download_name, as_attachment)
        partial["Cache-Control"] = "private, max-age=3600"
        return partial

    full = FileResponse(path.open("rb"), content_type=content_type)
    full["Content-Length"] = str(size)
    full["Accept-Ranges"] = "bytes"
    full["Content-Disposition"] = _disposition(download_name, as_attachment)
    full["Cache-Control"] = "private, max-age=3600"
    return full
