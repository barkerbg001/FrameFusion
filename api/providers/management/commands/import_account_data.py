from __future__ import annotations

from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from providers.account_import import import_database


class Command(BaseCommand):
    help = (
        "Import projects, history and settings from a multi-account FrameFusion database "
        "(for example an accounts-backup file). Safe to run more than once."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--from", dest="source", required=True, help="Path to the .sqlite3 file"
        )

    def handle(self, *args: Any, **options: Any) -> None:
        source = Path(options["source"])
        try:
            report = import_database(source)
        except (FileNotFoundError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        for line in report.lines():
            self.stdout.write(line)
        if report.choices_created:
            self.stdout.write(
                self.style.WARNING(
                    "Resolve the pending settings in Settings → Data or with "
                    "`resolve_import_conflicts`."
                )
            )
