"""Import chats exported from the old browser-only FrameFusion UI.

Export in the old UI's browser console:
    copy(localStorage.getItem("framefusion:chats"))
and save the clipboard to a .json file. The new Settings page can also import
them directly from the same browser.
"""

import json
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from pydantic import ValidationError

from studio.legacy import LegacyImport, import_chats


class Command(BaseCommand):
    help = "Import legacy localStorage chats (JSON) as projects."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--file", required=True, type=Path)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args: Any, **options: Any) -> None:
        path: Path = options["file"]
        if not path.is_file():
            raise CommandError(f"{path} does not exist.")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, str):
                raw = json.loads(raw)
            data = LegacyImport.model_validate(raw if "chats" in raw else {"chats": raw})
        except (ValueError, ValidationError, TypeError) as exc:
            raise CommandError(f"Not a valid FrameFusion chat export: {exc}") from exc

        report = import_chats(data, dry_run=options["dry_run"])
        prefix = "[dry run] " if options["dry_run"] else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix}Projects created: {report.projects_created}, skipped (already "
                f"imported or empty): {report.projects_skipped}, messages: "
                f"{report.messages_created}, media linked: {report.media_claimed}."
            )
        )
