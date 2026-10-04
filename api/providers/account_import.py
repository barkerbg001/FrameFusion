"""Import data from a database created by the earlier multi-account version.

Projects, conversations, jobs (with their events) and media rows are copied with
their original IDs and timestamps. Settings are grouped (each credential, the AI
defaults, each agent override, the theme). A group is applied automatically only
when every account agrees and nothing different is already configured; otherwise
an ``ImportedSettingChoice`` records the candidates and nothing changes until
someone picks one. The source database is opened read-only and never modified.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from django.db import connection, transaction
from django.utils import timezone

from common.http import ApiError

from .crypto import EncryptionUnavailable, decrypt_secret
from .models import (
    SERVICE_CHOICES,
    AgentModelOverride,
    AppSettings,
    ImportedSettingChoice,
    ProviderCredential,
)

KEEP_CURRENT = "keep_current"
SERVICE_LABELS = dict(SERVICE_CHOICES)
PERSONA_LABELS = {"planner": "Orchestrator and writing", "production": "Visual specialist"}


# --- Detection --------------------------------------------------------------------------------


def _open_readonly(path: Path) -> sqlite3.Connection:
    uri = f"{path.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')}


def is_account_era(path: Path) -> bool:
    """True if the SQLite file still has the per-account schema."""
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        conn = _open_readonly(path)
    except sqlite3.Error:
        return False
    try:
        tables = _tables(conn)
        if "auth_user" in tables or "accounts_userpreferences" in tables:
            return True
        if "studio_project" in tables and "owner_id" in _columns(conn, "studio_project"):
            return True
        return "providers_providercredential" in tables and "user_id" in _columns(
            conn, "providers_providercredential"
        )
    except sqlite3.Error:
        return False
    finally:
        conn.close()


# --- Report ------------------------------------------------------------------------------------


@dataclass
class ImportReport:
    projects: int = 0
    projects_skipped: int = 0
    messages: int = 0
    jobs: int = 0
    events: int = 0
    media: int = 0
    media_skipped: int = 0
    renamed_legacy_ids: int = 0
    settings_applied: list[str] = field(default_factory=list)
    settings_unchanged: list[str] = field(default_factory=list)
    choices_created: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        out = [
            f"Projects imported: {self.projects} (already present: {self.projects_skipped})",
            f"Messages imported: {self.messages}",
            f"Jobs imported: {self.jobs} with {self.events} events",
            f"Media items imported: {self.media} (already present: {self.media_skipped})",
        ]
        if self.renamed_legacy_ids:
            out.append(
                f"Legacy chat IDs prefixed with the account name to keep them unique: "
                f"{self.renamed_legacy_ids}"
            )
        if self.settings_applied:
            out.append("Settings applied: " + ", ".join(self.settings_applied))
        if self.settings_unchanged:
            out.append("Settings already matching: " + ", ".join(self.settings_unchanged))
        if self.choices_created:
            out.append("Settings that need a decision: " + ", ".join(self.choices_created))
        return out


# --- Data copy ---------------------------------------------------------------------------------


def _rows(conn: sqlite3.Connection, table: str, order: str = "") -> list[dict[str, Any]]:
    if table not in _tables(conn):
        return []
    sql = f'SELECT * FROM "{table}"' + (f" ORDER BY {order}" if order else "")
    return [dict(r) for r in conn.execute(sql)]


def _existing(sql: str) -> set[Any]:
    with connection.cursor() as cursor:
        cursor.execute(sql)
        return {r[0] for r in cursor.fetchall()}


def _insert(table: str, row: dict[str, Any]) -> None:
    columns = list(row)
    placeholders = ", ".join(["%s"] * len(columns))
    names = ", ".join(f'"{c}"' for c in columns)
    with connection.cursor() as cursor:
        cursor.execute(
            f'INSERT INTO "{table}" ({names}) VALUES ({placeholders})', [row[c] for c in columns]
        )


def _copy_studio(conn: sqlite3.Connection, users: dict[int, str], report: ImportReport) -> None:
    project_ids = _existing("SELECT id FROM studio_project")
    legacy_ids = _existing("SELECT legacy_id FROM studio_project WHERE legacy_id <> ''")
    new_projects: set[str] = set()

    for row in _rows(conn, "studio_project", "created_at"):
        if row["id"] in project_ids:
            report.projects_skipped += 1
            continue
        legacy_id = row.get("legacy_id") or ""
        if legacy_id and legacy_id in legacy_ids:
            prefixed = f"{users.get(row.get('owner_id') or 0, 'user')}:{legacy_id}"[:64]
            legacy_id = prefixed if prefixed not in legacy_ids else ""
            report.renamed_legacy_ids += 1
        if legacy_id:
            legacy_ids.add(legacy_id)
        _insert(
            "studio_project",
            {
                "id": row["id"],
                "title": row["title"],
                "title_locked": row["title_locked"],
                "legacy_id": legacy_id,
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            },
        )
        project_ids.add(row["id"])
        new_projects.add(row["id"])
        report.projects += 1

    job_ids = _existing("SELECT id FROM studio_generationjob")
    legacy_jobs = _rows(conn, "studio_generationjob", "created_at")
    all_job_ids = job_ids | {j["id"] for j in legacy_jobs}
    new_jobs: set[str] = set()
    for row in legacy_jobs:
        if row["id"] in job_ids:
            continue
        _insert(
            "studio_generationjob",
            {
                "id": row["id"],
                "project_id": row["project_id"] if row.get("project_id") in project_ids else None,
                "kind": row["kind"],
                "agent": row["agent"],
                "status": row["status"],
                "input": row["input"],
                "result": row["result"],
                "error": row["error"],
                "usage": row["usage"],
                "cancel_requested": row["cancel_requested"],
                "retry_of_id": row["retry_of_id"]
                if row.get("retry_of_id") in all_job_ids
                else None,
                "boot_id": row["boot_id"],
                "created_at": row["created_at"],
                "started_at": row["started_at"],
                "finished_at": row["finished_at"],
            },
        )
        new_jobs.add(row["id"])
        report.jobs += 1
    job_ids |= new_jobs

    for row in _rows(conn, "studio_jobevent", "job_id, seq"):
        if row["job_id"] not in new_jobs:
            continue
        row.pop("id", None)
        _insert("studio_jobevent", row)
        report.events += 1

    for row in _rows(conn, "studio_message", "created_at, id"):
        if row["project_id"] not in new_projects:
            continue
        row.pop("id", None)
        if row.get("job_id") not in job_ids:
            row["job_id"] = None
        _insert("studio_message", row)
        report.messages += 1

    media_names = _existing("SELECT file_name FROM studio_mediaasset")
    media_ids = _existing("SELECT id FROM studio_mediaasset")
    for row in _rows(conn, "studio_mediaasset", "created_at"):
        if row["file_name"] in media_names or row["id"] in media_ids:
            report.media_skipped += 1
            continue
        row.pop("owner_id", None)
        if row.get("project_id") not in project_ids:
            row["project_id"] = None
        if row.get("job_id") not in job_ids:
            row["job_id"] = None
        _insert("studio_mediaasset", row)
        media_names.add(row["file_name"])
        report.media += 1


# --- Settings ----------------------------------------------------------------------------------


@dataclass
class Candidate:
    id: str
    source: str
    summary: str
    value_key: str
    payload: dict[str, Any]


def _plain_key(encrypted: str) -> str | None:
    try:
        return decrypt_secret(encrypted)
    except EncryptionUnavailable:
        return None


def _credential_summary(row: dict[str, Any]) -> str:
    hint = f"••••{row['key_hint']}" if row.get("key_hint") else "••••"
    status = row.get("last_test_status") or "untested"
    return f"{hint} ({'tested OK' if status == 'valid' else status})"


def _ai_summary(provider: str, model: str, temperature: Any, tokens: Any) -> str:
    if not provider:
        return "No default provider"
    parts = [f"{SERVICE_LABELS.get(provider, provider)} · {model or 'no model'}"]
    if temperature is not None:
        parts.append(f"temperature {temperature}")
    if tokens:
        parts.append(f"max {tokens} tokens")
    return ", ".join(parts)


def _decide(
    group: str,
    label: str,
    candidates: list[Candidate],
    current_key: str | None,
    current_summary: str,
    apply: Callable[[dict[str, Any]], None],
    source: str,
    report: ImportReport,
) -> None:
    if not candidates:
        return
    if ImportedSettingChoice.objects.filter(
        group=group, status=ImportedSettingChoice.Status.PENDING
    ).exists():
        report.choices_created.append(f"{label} (already pending)")
        return
    distinct: dict[str, Candidate] = {}
    sources: dict[str, list[str]] = {}
    for candidate in candidates:
        distinct.setdefault(candidate.value_key, candidate)
        sources.setdefault(candidate.value_key, []).append(candidate.source)
    if len(distinct) == 1:
        only = next(iter(distinct.values()))
        if current_key == only.value_key:
            report.settings_unchanged.append(label)
            return
        if current_key is None:
            apply(only.payload)
            report.settings_applied.append(label)
            return
    ImportedSettingChoice.objects.create(
        group=group,
        label=label,
        current_summary=current_summary if current_key is not None else "",
        source=source,
        candidates=[
            {
                "id": c.id,
                "source": ", ".join(sources[key]),
                "summary": c.summary,
                "payload": c.payload,
            }
            for key, c in distinct.items()
        ],
    )
    report.choices_created.append(label)


def _apply_credential(service: str) -> Callable[[dict[str, Any]], None]:
    def apply(payload: dict[str, Any]) -> None:
        ProviderCredential.objects.update_or_create(provider=service, defaults=payload)

    return apply


def _apply_ai_defaults(payload: dict[str, Any]) -> None:
    app = AppSettings.load()
    for key, value in payload.items():
        setattr(app, key, value)
    app.save()


def _apply_override(persona: str) -> Callable[[dict[str, Any]], None]:
    def apply(payload: dict[str, Any]) -> None:
        AgentModelOverride.objects.update_or_create(persona=persona, defaults=payload)

    return apply


def _apply_theme(payload: dict[str, Any]) -> None:
    app = AppSettings.load()
    app.theme = payload["theme"]
    app.save(update_fields=["theme", "updated_at"])


def apply_group(group: str, payload: dict[str, Any]) -> None:
    if group.startswith("credential:"):
        _apply_credential(group.split(":", 1)[1])(payload)
    elif group == "ai_defaults":
        _apply_ai_defaults(payload)
    elif group.startswith("override:"):
        _apply_override(group.split(":", 1)[1])(payload)
    elif group == "theme":
        _apply_theme(payload)
    else:
        raise ValueError(f"Unknown setting group {group}")


def _import_settings(
    conn: sqlite3.Connection, users: dict[int, str], source: str, report: ImportReport
) -> None:
    def who(row: dict[str, Any]) -> str:
        return users.get(row.get("user_id") or 0, f"user {row.get('user_id')}")

    # Credentials
    by_service: dict[str, list[dict[str, Any]]] = {}
    for row in _rows(conn, "providers_providercredential", "user_id"):
        if row["provider"] in SERVICE_LABELS:
            by_service.setdefault(row["provider"], []).append(row)
    for service, rows in by_service.items():
        candidates = []
        for row in rows:
            plain = _plain_key(row["encrypted_key"])
            candidates.append(
                Candidate(
                    id=f"u{row['user_id']}",
                    source=who(row),
                    summary=_credential_summary(row),
                    value_key=f"plain:{plain}"
                    if plain is not None
                    else f"enc:{row['encrypted_key']}",
                    payload={
                        "encrypted_key": row["encrypted_key"],
                        "key_hint": row.get("key_hint") or "",
                        "last_test_status": row.get("last_test_status") or "untested",
                        "last_test_message": row.get("last_test_message") or "",
                    },
                )
            )
        current = ProviderCredential.objects.filter(provider=service).first()
        current_key = None
        current_summary = ""
        if current is not None:
            plain = _plain_key(current.encrypted_key)
            current_key = f"plain:{plain}" if plain is not None else f"enc:{current.encrypted_key}"
            current_summary = _credential_summary(
                {"key_hint": current.key_hint, "last_test_status": current.last_test_status}
            )
        _decide(
            f"credential:{service}",
            f"{SERVICE_LABELS[service]} API key",
            candidates,
            current_key,
            current_summary,
            _apply_credential(service),
            source,
            report,
        )

    app = AppSettings.load()

    # AI defaults
    candidates = []
    for row in _rows(conn, "providers_aipreferences", "user_id"):
        payload: dict[str, Any] = {
            "default_provider": row.get("default_provider") or "",
            "default_model": row.get("default_model") or "",
            "temperature": row.get("temperature"),
            "max_output_tokens": row.get("max_output_tokens"),
        }
        if (
            not payload["default_provider"]
            and payload["temperature"] is None
            and not payload["max_output_tokens"]
        ):
            continue
        candidates.append(
            Candidate(
                id=f"u{row['user_id']}",
                source=who(row),
                summary=_ai_summary(
                    payload["default_provider"],
                    payload["default_model"],
                    payload["temperature"],
                    payload["max_output_tokens"],
                ),
                value_key=json.dumps(payload, sort_keys=True),
                payload=payload,
            )
        )
    current_ai = {
        "default_provider": app.default_provider,
        "default_model": app.default_model,
        "temperature": app.temperature,
        "max_output_tokens": app.max_output_tokens,
    }
    ai_is_set = (
        bool(app.default_provider) or app.temperature is not None or bool(app.max_output_tokens)
    )
    _decide(
        "ai_defaults",
        "Default AI provider and model",
        candidates,
        json.dumps(current_ai, sort_keys=True) if ai_is_set else None,
        _ai_summary(*current_ai.values()),
        _apply_ai_defaults,
        source,
        report,
    )

    # Agent overrides
    by_persona: dict[str, list[Candidate]] = {}
    for row in _rows(conn, "providers_agentmodeloverride", "user_id"):
        payload = {"provider": row["provider"], "model": row["model"]}
        by_persona.setdefault(row["persona"], []).append(
            Candidate(
                id=f"u{row['user_id']}",
                source=who(row),
                summary=f"{SERVICE_LABELS.get(row['provider'], row['provider'])} · {row['model']}",
                value_key=json.dumps(payload, sort_keys=True),
                payload=payload,
            )
        )
    for persona, persona_candidates in by_persona.items():
        if persona not in PERSONA_LABELS:
            continue
        existing = AgentModelOverride.objects.filter(persona=persona).first()
        current_payload = (
            {"provider": existing.provider, "model": existing.model} if existing else None
        )
        _decide(
            f"override:{persona}",
            f"{PERSONA_LABELS[persona]} model override",
            persona_candidates,
            json.dumps(current_payload, sort_keys=True) if current_payload else None,
            (
                f"{SERVICE_LABELS.get(existing.provider, existing.provider)} · {existing.model}"
                if existing
                else ""
            ),
            _apply_override(persona),
            source,
            report,
        )

    # Theme
    candidates = [
        Candidate(
            id=f"u{row['user_id']}",
            source=who(row),
            summary=str(row["theme"]).capitalize(),
            value_key=str(row["theme"]),
            payload={"theme": row["theme"]},
        )
        for row in _rows(conn, "accounts_userpreferences", "user_id")
        if row.get("theme") in {"dark", "light", "system"} and row["theme"] != "system"
    ]
    _decide(
        "theme",
        "Theme",
        candidates,
        app.theme if app.theme != "system" else None,
        app.theme.capitalize(),
        _apply_theme,
        source,
        report,
    )


# --- Entry points ------------------------------------------------------------------------------


def import_database(path: Path) -> ImportReport:
    if not path.exists():
        raise FileNotFoundError(f"{path} does not exist.")
    conn = _open_readonly(path)
    report = ImportReport()
    try:
        tables = _tables(conn)
        if "studio_project" not in tables and "providers_providercredential" not in tables:
            raise ValueError(f"{path.name} does not look like a FrameFusion database.")
        users = (
            {r["id"]: r["username"] for r in _rows(conn, "auth_user")}
            if "auth_user" in tables
            else {}
        )
        with transaction.atomic():
            _copy_studio(conn, users, report)
            _import_settings(conn, users, path.name, report)
    finally:
        conn.close()
    return report


def pending_choices_payload() -> list[dict[str, Any]]:
    return [
        {
            "id": choice.id,
            "group": choice.group,
            "label": choice.label,
            "current_summary": choice.current_summary,
            "source": choice.source,
            "created_at": choice.created_at.isoformat(),
            "candidates": [
                {"id": c["id"], "source": c["source"], "summary": c["summary"]}
                for c in choice.candidates
            ],
        }
        for choice in ImportedSettingChoice.objects.filter(
            status=ImportedSettingChoice.Status.PENDING
        )
    ]


def resolve_choice(choice_id: int, selection: str) -> ImportedSettingChoice:
    with transaction.atomic():
        choice = (
            ImportedSettingChoice.objects.select_for_update()
            .filter(pk=choice_id, status=ImportedSettingChoice.Status.PENDING)
            .first()
        )
        if choice is None:
            raise ApiError("That choice was already resolved or does not exist.", status_code=404)
        if selection == KEEP_CURRENT:
            resolution = KEEP_CURRENT
        else:
            match = next((c for c in choice.candidates if c["id"] == selection), None)
            if match is None:
                raise ApiError("Pick one of the listed options.", code="invalid_choice")
            apply_group(choice.group, match["payload"])
            resolution = f"{match['id']} ({match['source']})"
        choice.status = ImportedSettingChoice.Status.RESOLVED
        choice.resolution = resolution[:80]
        choice.resolved_at = timezone.now()
        choice.candidates = [
            {"id": c["id"], "source": c["source"], "summary": c["summary"]}
            for c in choice.candidates
        ]
        choice.save()
    return choice
