from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from common.http import ApiError
from providers.account_import import KEEP_CURRENT, pending_choices_payload, resolve_choice


class Command(BaseCommand):
    help = (
        "List or resolve settings that differed between accounts in an imported database. "
        "Nothing is applied until you choose."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--list", action="store_true", help="Show pending choices")
        parser.add_argument(
            "--choose",
            action="append",
            default=[],
            metavar="GROUP=OPTION",
            help=f"Pick an option, e.g. credential:openrouter=u2 or theme={KEEP_CURRENT}",
        )
        parser.add_argument(
            "--prefer",
            metavar="USERNAME",
            help="Pick the named account's value for every pending group where it has one",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        pending = {c["group"]: c for c in pending_choices_payload()}
        if options["list"] or not (options["choose"] or options["prefer"]):
            if not pending:
                self.stdout.write("No settings are waiting for a decision.")
                return
            for choice in pending.values():
                self.stdout.write(f"{choice['group']}  —  {choice['label']}")
                current = choice["current_summary"] or "not set"
                self.stdout.write(f"    {KEEP_CURRENT}: keep current ({current})")
                for candidate in choice["candidates"]:
                    self.stdout.write(
                        f"    {candidate['id']}: {candidate['summary']}  [{candidate['source']}]"
                    )
            return

        selections: dict[str, str] = {}
        if options["prefer"]:
            name = options["prefer"]
            for group, choice in pending.items():
                for candidate in choice["candidates"]:
                    if name in [s.strip() for s in candidate["source"].split(",")]:
                        selections[group] = candidate["id"]
        for item in options["choose"]:
            group, sep, option = item.partition("=")
            if not sep:
                raise CommandError(f"Use GROUP=OPTION, got {item!r}.")
            selections[group.strip()] = option.strip()

        for group, option in selections.items():
            target = pending.get(group)
            if target is None:
                raise CommandError(f"No pending choice for {group!r}. Use --list.")
            try:
                resolve_choice(target["id"], option)
            except ApiError as exc:
                raise CommandError(f"{group}: {exc.message}") from exc
            self.stdout.write(self.style.SUCCESS(f"{group}: applied {option}"))
