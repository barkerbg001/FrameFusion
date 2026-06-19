import re
import unicodedata


EXPLICIT_NAME_PATTERNS = (
    re.compile(
        r"(?:save as|saved as|named|call it|file name|filename|output name)"
        r"\s+['\"]?([^\s'\"]+\.mp4)['\"]?",
        re.IGNORECASE,
    ),
    re.compile(
        r"output_name\s*[:=]\s*['\"]?([^\s'\"]+\.mp4)['\"]?",
        re.IGNORECASE,
    ),
)

TASK_PREFIXES = (
    "create a",
    "create an",
    "create",
    "make a",
    "make an",
    "make",
    "generate a",
    "generate an",
    "generate",
    "produce a",
    "produce an",
    "produce",
    "build a",
    "build an",
    "build",
    "short about",
    "short for",
    "short on",
    "video about",
    "video for",
    "video on",
    "briefing about",
    "briefing for",
    "briefing on",
)


def _validate_safe_filename(output_name: str) -> str:
    normalized = output_name.strip()
    if (
        not normalized
        or normalized != normalized.split("/")[-1]
        or normalized != normalized.split("\\")[-1]
        or not normalized.lower().endswith(".mp4")
    ):
        raise ValueError("Generated filename must be an .mp4 name without a path")
    return normalized


def slugify_filename(text: str, max_stem_length: int = 48) -> str:
    """Turn free text into a safe mp4 filename stem."""
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_text.lower()).strip("-")
    if not slug:
        slug = "video"
    if len(slug) > max_stem_length:
        slug = slug[:max_stem_length].rstrip("-")
    return f"{slug}.mp4"


def extract_output_name_from_text(text: str) -> str | None:
    """Return an explicit .mp4 name mentioned in the source text, if any."""
    for pattern in EXPLICIT_NAME_PATTERNS:
        match = pattern.search(text)
        if match:
            return _validate_safe_filename(match.group(1))
    return None


def _clean_task_for_slug(text: str) -> str:
    cleaned = " ".join(text.strip().split())
    for prefix in TASK_PREFIXES:
        cleaned = re.sub(
            rf"^{re.escape(prefix)}\s+",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
    return cleaned.strip(" .,-")


def resolve_output_name(source_text: str, default_stem: str = "short") -> str:
    """Derive an mp4 filename from task or script text."""
    combined = " ".join(source_text.strip().split())
    explicit = extract_output_name_from_text(combined) if combined else None
    if explicit:
        return explicit

    cleaned = _clean_task_for_slug(combined) if combined else ""
    if cleaned:
        return slugify_filename(cleaned)

    return _validate_safe_filename(f"{default_stem}.mp4")
