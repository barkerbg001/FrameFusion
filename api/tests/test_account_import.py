"""Upgrading a database from the multi-account version."""

import json
import sqlite3
import uuid
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from django.core.management import call_command
from rest_framework.test import APIClient

from providers import services
from providers.account_import import import_database, is_account_era
from providers.crypto import decrypt_secret, encrypt_secret
from providers.models import (
    AgentModelOverride,
    AppSettings,
    ImportedSettingChoice,
    ProviderCredential,
)
from studio.models import GenerationJob, JobEvent, MediaAsset, Message, Project

pytestmark = pytest.mark.django_db

SCHEMA = Path(__file__).parent / "fixtures" / "account_era_schema.sql"
NOW = "2025-05-01 10:00:00"
ALICE_KEY = "sk-or-v1-" + "a" * 32
BOB_KEY = "sk-or-v1-" + "b" * 32
GEMINI_KEY = "AIza" + "g" * 35


def _legacy_db(path: Path) -> dict[str, str]:
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    for uid, name in ((1, "alice"), (2, "bob")):
        conn.execute(
            "INSERT INTO auth_user (id, password, is_superuser, username, last_name, email, "
            "is_staff, is_active, date_joined, first_name) "
            "VALUES (?, '!', 0, ?, '', '', 0, 1, ?, '')",
            (uid, name, NOW),
        )
    ids = {k: uuid.uuid4().hex for k in ("p1", "p2", "j1", "j2", "m1")}
    projects = [
        (ids["p1"], "Tide pools", 1, "chat-1", "2025-01-01 09:00:00", "2025-01-02 09:00:00", 1),
        (ids["p2"], "Bob's teaser", 0, "chat-1", "2025-02-01 09:00:00", "2025-02-02 09:00:00", 2),
    ]
    conn.executemany(
        "INSERT INTO studio_project (id, title, title_locked, legacy_id, created_at, updated_at, "
        "owner_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
        projects,
    )
    conn.execute(
        "INSERT INTO studio_generationjob (id, kind, agent, status, input, result, error, usage, "
        "cancel_requested, boot_id, created_at, started_at, finished_at, owner_id, retry_of_id, "
        "project_id) VALUES (?, 'chat', 'framey', 'succeeded', '{}', '{\"content\": \"ok\"}', "
        "NULL, '[]', 0, 'b', ?, ?, ?, 1, NULL, ?)",
        (ids["j1"], NOW, NOW, NOW, ids["p1"]),
    )
    conn.execute(
        "INSERT INTO studio_generationjob (id, kind, agent, status, input, result, error, usage, "
        "cancel_requested, boot_id, created_at, started_at, finished_at, owner_id, retry_of_id, "
        "project_id) VALUES (?, 'chat', 'framey', 'failed', '{}', NULL, '{}', '[]', 0, 'b', ?, "
        "NULL, ?, 1, ?, ?)",
        (ids["j2"], NOW, NOW, ids["j1"], ids["p1"]),
    )
    conn.executemany(
        "INSERT INTO studio_jobevent (seq, type, agent, persona, message, data, created_at, "
        "job_id) VALUES (?, 'status', '', '', ?, '{}', ?, ?)",
        [(1, "Started", NOW, ids["j1"]), (2, "Finished", NOW, ids["j1"])],
    )
    conn.executemany(
        "INSERT INTO studio_message (role, content, persona, attachments, created_at, job_id, "
        "project_id) VALUES (?, ?, ?, '[]', ?, ?, ?)",
        [
            (
                "user",
                "Make a short about tide pools",
                "",
                "2025-01-01 09:01:00",
                ids["j1"],
                ids["p1"],
            ),
            ("assistant", "Here is a plan", "planner", "2025-01-01 09:02:00", ids["j1"], ids["p1"]),
            ("user", "Bob's idea", "", "2025-02-01 09:01:00", None, ids["p2"]),
        ],
    )
    conn.execute(
        "INSERT INTO studio_mediaasset (id, kind, file_name, display_name, duration_seconds, "
        "size_bytes, created_at, job_id, owner_id, project_id) VALUES (?, 'video', "
        "'abc_tide.mp4', 'tide.mp4', 12.5, 100, ?, ?, 1, ?)",
        (ids["m1"], NOW, ids["j1"], ids["p1"]),
    )
    creds = [
        ("openrouter", encrypt_secret(ALICE_KEY), "aaaa", "valid", 1),
        ("openrouter", encrypt_secret(BOB_KEY), "bbbb", "untested", 2),
        ("gemini", encrypt_secret(GEMINI_KEY), "gggg", "valid", 1),
        ("gemini", encrypt_secret(GEMINI_KEY), "gggg", "untested", 2),
    ]
    conn.executemany(
        "INSERT INTO providers_providercredential (provider, encrypted_key, key_hint, "
        "last_test_status, last_test_message, last_tested_at, created_at, updated_at, user_id) "
        "VALUES (?, ?, ?, ?, '', NULL, ?, ?, ?)",
        [(p, k, h, s, NOW, NOW, u) for p, k, h, s, u in creds],
    )
    conn.executemany(
        "INSERT INTO providers_aipreferences (default_provider, default_model, temperature, "
        "max_output_tokens, updated_at, user_id) VALUES (?, ?, ?, NULL, ?, ?)",
        [
            ("openrouter", "openai/gpt-4o-mini", 0.5, NOW, 1),
            ("openrouter", "anthropic/x", None, NOW, 2),
        ],
    )
    conn.execute(
        "INSERT INTO providers_agentmodeloverride (persona, provider, model, updated_at, user_id) "
        "VALUES ('production', 'gemini', 'gemini-flash-latest', ?, 1)",
        (NOW,),
    )
    conn.executemany(
        "INSERT INTO accounts_userpreferences (theme, updated_at, user_id) VALUES (?, ?, ?)",
        [("dark", NOW, 1), ("system", NOW, 2)],
    )
    conn.commit()
    conn.close()
    return ids


def test_detection(tmp_path: Path) -> None:
    legacy = tmp_path / "old.sqlite3"
    _legacy_db(legacy)
    assert is_account_era(legacy)
    assert not is_account_era(tmp_path / "missing.sqlite3")
    fresh = tmp_path / "fresh.sqlite3"
    sqlite3.connect(fresh).execute("CREATE TABLE studio_project (id char(32))").connection.close()
    assert not is_account_era(fresh)


def test_import_preserves_history_and_asks_about_conflicts(tmp_path: Path) -> None:
    legacy = tmp_path / "old.sqlite3"
    ids = _legacy_db(legacy)
    report = import_database(legacy)

    assert report.projects == 2 and report.messages == 3
    assert report.jobs == 2 and report.events == 2 and report.media == 1
    assert report.renamed_legacy_ids == 1

    tide = Project.objects.get(pk=uuid.UUID(ids["p1"]))
    assert tide.title == "Tide pools" and tide.legacy_id == "chat-1"
    assert tide.updated_at.isoformat().startswith("2025-01-02T09:00:00")
    assert Project.objects.get(pk=uuid.UUID(ids["p2"])).legacy_id == "bob:chat-1"
    assert [m.content for m in tide.messages.order_by("created_at")] == [
        "Make a short about tide pools",
        "Here is a plan",
    ]
    retry = GenerationJob.objects.get(pk=uuid.UUID(ids["j2"]))
    assert str(retry.retry_of_id).replace("-", "") == ids["j1"]
    assert JobEvent.objects.filter(job_id=uuid.UUID(ids["j1"])).count() == 2
    assert MediaAsset.objects.get().project_id == tide.pk

    # Identical Gemini keys and a single override/theme are applied automatically.
    assert decrypt_secret(ProviderCredential.objects.get(provider="gemini").encrypted_key) == (
        GEMINI_KEY
    )
    assert AgentModelOverride.objects.get(persona="production").model == "gemini-flash-latest"
    assert AppSettings.load().theme == "dark"

    # Different OpenRouter keys and AI defaults are not chosen silently.
    assert not ProviderCredential.objects.filter(provider="openrouter").exists()
    assert AppSettings.load().default_provider == ""
    pending = {c.group: c for c in ImportedSettingChoice.objects.filter(status="pending")}
    assert set(pending) == {"credential:openrouter", "ai_defaults"}
    sources = {c["source"] for c in pending["credential:openrouter"].candidates}
    assert sources == {"alice", "bob"}

    # Re-running is idempotent.
    again = import_database(legacy)
    assert again.projects == 0 and again.projects_skipped == 2 and again.media_skipped == 1
    assert Message.objects.count() == 3
    assert ImportedSettingChoice.objects.filter(status="pending").count() == 2


def test_conflicts_are_resolved_explicitly_via_api(tmp_path: Path, client: APIClient) -> None:
    legacy = tmp_path / "old.sqlite3"
    _legacy_db(legacy)
    import_database(legacy)

    listing = client.get("/api/settings/import-conflicts").json()["choices"]
    assert client.get("/api/app").json()["pending_import_choices"] == 2
    raw = json.dumps(listing)
    assert "payload" not in raw and "encrypted_key" not in raw
    assert ALICE_KEY not in raw and BOB_KEY not in raw
    credential = next(c for c in listing if c["group"] == "credential:openrouter")
    bob = next(c for c in credential["candidates"] if c["source"] == "bob")
    assert "bbbb" in bob["summary"]

    bad = client.post(
        f"/api/settings/import-conflicts/{credential['id']}", {"choice": "u99"}, format="json"
    )
    assert bad.status_code == 400

    remaining = client.post(
        f"/api/settings/import-conflicts/{credential['id']}", {"choice": bob["id"]}, format="json"
    ).json()["choices"]
    assert services.get_api_key("openrouter") == BOB_KEY
    resolved = ImportedSettingChoice.objects.get(pk=credential["id"])
    assert resolved.status == "resolved"
    assert all("payload" not in c for c in resolved.candidates)

    defaults = remaining[0]
    client.post(
        f"/api/settings/import-conflicts/{defaults['id']}",
        {"choice": "keep_current"},
        format="json",
    )
    assert AppSettings.load().default_provider == ""
    assert client.get("/api/settings/import-conflicts").json()["choices"] == []
    again = client.post(
        f"/api/settings/import-conflicts/{defaults['id']}",
        {"choice": "keep_current"},
        format="json",
    )
    assert again.status_code == 404


def test_cli_resolution_and_existing_values_are_respected(tmp_path: Path) -> None:
    services.save_api_key("gemini", "AIza" + "z" * 35)
    legacy = tmp_path / "old.sqlite3"
    _legacy_db(legacy)
    import_database(legacy)

    pending = set(
        ImportedSettingChoice.objects.filter(status="pending").values_list("group", flat=True)
    )
    assert "credential:gemini" in pending

    out = StringIO()
    call_command("resolve_import_conflicts", "--list", stdout=out)
    assert "credential:gemini" in out.getvalue() and "keep_current" in out.getvalue()

    call_command("resolve_import_conflicts", "--prefer", "alice", stdout=StringIO())
    assert services.get_api_key("openrouter") == ALICE_KEY
    assert services.get_api_key("gemini") == GEMINI_KEY
    assert AppSettings.load().default_model == "openai/gpt-4o-mini"
    assert not ImportedSettingChoice.objects.filter(status="pending").exists()


def test_upgrade_command_backs_up_and_imports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    legacy = tmp_path / "framefusion.sqlite3"
    _legacy_db(legacy)
    command = "providers.management.commands.upgrade_single_user"
    fake_settings = SimpleNamespace(DATABASES={"default": {"NAME": legacy}})
    monkeypatch.setattr(f"{command}.settings", fake_settings)

    calls: list[str] = []
    monkeypatch.setattr(f"{command}.connections.close_all", lambda: None)
    monkeypatch.setattr(f"{command}.call_command", lambda name, **kwargs: calls.append(name))
    imported: list[Path] = []

    def fake_import(path: Path) -> Any:
        imported.append(path)
        return import_database(path)

    monkeypatch.setattr(f"{command}.import_database", fake_import)
    out = StringIO()
    call_command("upgrade_single_user", stdout=out)
    backups = list(tmp_path.glob("framefusion.accounts-backup-*.sqlite3"))
    assert len(backups) == 1
    assert not legacy.exists()
    assert calls == ["migrate"]
    assert imported == backups
    assert "Settings that need a decision" in out.getvalue()
    assert Project.objects.count() == 2

    fake_settings.DATABASES["default"]["NAME"] = backups[0].with_name("fresh.sqlite3")
    out = StringIO()
    call_command("upgrade_single_user", stdout=out)
    assert "already" in out.getvalue()
