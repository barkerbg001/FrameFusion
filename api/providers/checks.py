from __future__ import annotations

from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.checks import Error, register

from .account_import import is_account_era


@register()
def legacy_account_database(app_configs: Any = None, **kwargs: Any) -> list[Error]:
    name = settings.DATABASES["default"].get("NAME")
    if not name or str(name).startswith(":memory:") or "mode=memory" in str(name):
        return []
    if not is_account_era(Path(name)):
        return []
    return [
        Error(
            "The database was created by the earlier multi-account version of FrameFusion.",
            hint=(
                "Run `npm run migrate` (or `manage.py upgrade_single_user`). It backs up the "
                "current file, creates a single-user database and imports your projects, "
                "history and settings."
            ),
            id="framefusion.E001",
        )
    ]
