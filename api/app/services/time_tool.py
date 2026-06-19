from datetime import datetime
from typing import Any, Dict
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def get_current_time(timezone_name: str = "UTC") -> Dict[str, Any]:
    """Return the current date and time in an IANA timezone."""
    normalized = timezone_name.strip()
    if not normalized:
        raise ValueError("timezone must not be blank")

    try:
        current = datetime.now(ZoneInfo(normalized))
    except ZoneInfoNotFoundError as exc:
        raise ValueError(
            f"Unknown timezone '{timezone_name}'. Use an IANA timezone such as "
            "Africa/Johannesburg or America/New_York."
        ) from exc

    return {
        "timezone": normalized,
        "date": current.date().isoformat(),
        "time": current.strftime("%H:%M:%S"),
        "day_of_week": current.strftime("%A"),
        "iso_datetime": current.isoformat(timespec="seconds"),
        "utc_offset": current.strftime("%z")[:3] + ":" + current.strftime("%z")[3:],
    }
