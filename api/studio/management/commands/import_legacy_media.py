"""Add rendered files from the output folder to the media library.

Files already in the library are skipped. Nothing is moved or deleted.
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from engine.paths import GENERATED_DIR
from studio.legacy import register_untracked_media


class Command(BaseCommand):
    help = "Register media files in FRAMEFUSION_OUTPUT_DIR that are not in the library yet."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args: Any, **options: Any) -> None:
        report = register_untracked_media(dry_run=options["dry_run"])
        prefix = "[dry run] " if options["dry_run"] else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix}Scanned {GENERATED_DIR}. Added {report.media_claimed} file(s); "
                f"skipped {report.media_skipped} already in the library."
            )
        )
