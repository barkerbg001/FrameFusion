from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connections

from providers.account_import import import_database, is_account_era


class Command(BaseCommand):
    help = (
        "Upgrade a database from the multi-account version: back it up, create a fresh "
        "single-user database and import projects, history and settings. Does nothing if "
        "the database is already single-user."
    )
    requires_system_checks: list[str] = []

    def handle(self, *args: Any, **options: Any) -> None:
        db_path = Path(settings.DATABASES["default"]["NAME"])
        if not is_account_era(db_path):
            self.stdout.write("Database is already in the single-user format.")
            return

        connections.close_all()
        try:
            conn = sqlite3.connect(db_path)
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.close()
        except sqlite3.Error as exc:
            raise CommandError(
                f"Could not open {db_path.name}. Stop the API server and try again. ({exc})"
            ) from exc

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = db_path.with_name(f"{db_path.stem}.accounts-backup-{stamp}{db_path.suffix}")
        try:
            shutil.move(db_path, backup)
            for suffix in ("-wal", "-shm"):
                side = Path(f"{db_path}{suffix}")
                if side.exists():
                    shutil.move(side, Path(f"{backup}{suffix}"))
        except OSError as exc:
            raise CommandError(
                f"Could not move {db_path.name} aside. Stop the API server and try again. ({exc})"
            ) from exc
        self.stdout.write(f"Backed up the old database to {backup.name}.")

        call_command("migrate", interactive=False, verbosity=0)
        report = import_database(backup)
        for line in report.lines():
            self.stdout.write(f"  {line}")
        if report.choices_created:
            self.stdout.write(
                self.style.WARNING(
                    "Some settings differed between accounts and were not applied. Choose "
                    "which to keep in Settings → Data, or run "
                    "`npm run manage -- resolve_import_conflicts --list`."
                )
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"Upgrade complete. The backup {backup.name} is kept; delete it once you have "
                "checked your projects."
            )
        )
