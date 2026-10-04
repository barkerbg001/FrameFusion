import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from rest_framework.test import APIClient

from engine.llm import CompletionResult, LLMError
from studio import jobs
from studio.media import register_asset
from studio.models import GenerationJob, MediaAsset, Message, Project

from .conftest import FakeRegistry, configure_ai

pytestmark = pytest.mark.django_db

KEY = "sk-or-v1-0123456789abcdef0123"  # gitleaks:allow (dummy)


def _project(client: APIClient, title: str | None = None) -> dict[str, Any]:
    response = client.post("/api/projects", {"title": title} if title else {}, format="json")
    assert response.status_code == 201
    return response.json()


def test_project_crud(client: APIClient) -> None:
    project = _project(client)
    assert project["title"] == "Untitled project"
    assert client.get("/api/projects").json()[0]["id"] == project["id"]
    renamed = client.patch(
        f"/api/projects/{project['id']}", {"title": "Launch teaser"}, format="json"
    ).json()
    assert renamed["title"] == "Launch teaser"
    assert renamed["title_locked"] is True
    assert client.delete(f"/api/projects/{project['id']}").status_code == 204
    assert client.get(f"/api/projects/{project['id']}").status_code == 404


def test_project_list_reports_stage_from_recorded_work(client: APIClient) -> None:
    idea = Project.objects.create(title="Idea")
    developing = Project.objects.create(title="Developing")
    Message.objects.create(project=developing, role="user", content="Draft")
    failed = Project.objects.create(title="Failed")
    GenerationJob.objects.create(
        project=failed, kind=GenerationJob.Kind.PRODUCTION, status=GenerationJob.Status.FAILED
    )
    running = Project.objects.create(title="Running")
    GenerationJob.objects.create(
        project=running, kind=GenerationJob.Kind.RENDER, status=GenerationJob.Status.RUNNING
    )
    delivered = Project.objects.create(title="Delivered")
    MediaAsset.objects.create(
        project=delivered, kind=MediaAsset.Kind.VIDEO, file_name="cut.mp4", display_name="cut.mp4"
    )

    stages = {item["id"]: item["stage"] for item in client.get("/api/projects").json()}
    assert stages[str(idea.pk)] == "idea"
    assert stages[str(developing.pk)] == "developing"
    assert stages[str(failed.pk)] == "needs_attention"
    assert stages[str(running.pk)] == "in_production"
    assert stages[str(delivered.pk)] == "delivered"
    assert client.get(f"/api/projects/{idea.pk}").json()["stage"] is None


def test_chat_message_runs_orchestrator_in_background(
    client: APIClient, fake_providers: FakeRegistry
) -> None:
    configure_ai(key=KEY)
    fake_providers.get("openrouter").responses = [
        CompletionResult(text="Here is a plan for your short.", input_tokens=40, output_tokens=12)
    ]
    project = _project(client)

    response = client.post(
        f"/api/projects/{project['id']}/messages",
        {"content": "Suggest three angles for a story about tide pools"},
        format="json",
    )
    assert response.status_code == 202
    body = response.json()
    assert body["message"]["role"] == "user"
    assert body["project"]["title"] == "Suggest three angles for a story about tide pools"
    job = body["job"]
    assert job["status"] == "succeeded", job["error"]
    assert job["result"]["content"] == "Here is a plan for your short."
    assert job["usage"] == [
        {
            "provider": "openrouter",
            "model": "openai/gpt-4o-mini",
            "calls": 1,
            "input_tokens": 40,
            "output_tokens": 12,
        }
    ]
    event_types = [e["type"] for e in job["events"]]
    assert event_types[0] == "status" and "thinking" in event_types

    detail = client.get(f"/api/projects/{project['id']}").json()
    roles = [(m["role"], m["persona"]) for m in detail["messages"]]
    assert roles == [("user", None), ("assistant", "director")]
    thinking = next(e for e in job["events"] if e["type"] == "thinking")
    assert thinking["agent"] == "orchestrator" and thinking["persona"] == "director"
    assert thinking["message"].startswith("Director is thinking it through")
    assert fake_providers.used_keys["openrouter"] == KEY

    polled = client.get(f"/api/jobs/{job['id']}?after=1").json()
    assert all(e["seq"] > 1 for e in polled["events"])
    assert KEY not in json.dumps(polled)


def test_chat_blocked_with_guidance_when_not_configured(client: APIClient) -> None:
    project = _project(client)
    response = client.post(
        f"/api/projects/{project['id']}/messages", {"content": "Hello"}, format="json"
    )
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "not_configured"
    assert body["settings_path"] == "#/settings"
    assert body["readiness"]["planner"]["ready"] is False
    assert not Message.objects.exists()


def test_provider_errors_are_normalized_on_the_job(
    client: APIClient, fake_providers: FakeRegistry
) -> None:
    configure_ai(key=KEY)
    fake_providers.get("openrouter").responses = [
        LLMError(
            "OpenRouter: Rate limit reached. Wait a moment and try again.",
            kind="rate_limited",
            provider="openrouter",
            status_code=429,
            retryable=True,
        )
    ]
    project = _project(client)
    job = client.post(
        f"/api/projects/{project['id']}/messages", {"content": "Make a teaser"}, format="json"
    ).json()["job"]
    assert job["status"] == "failed"
    assert job["error"]["kind"] == "rate_limited"
    assert job["error"]["retryable"] is True
    assert KEY not in json.dumps(job)

    retry = client.post(f"/api/jobs/{job['id']}/retry")
    assert retry.status_code == 202
    retried = retry.json()
    assert retried["retry_of"] == job["id"]
    assert retried["status"] == "succeeded"
    user_message = Message.objects.get(role="user")
    assert str(user_message.job_id) == retried["id"]


def test_one_active_job_per_project(client: APIClient, settings: Any) -> None:
    configure_ai(key=KEY)
    project = Project.objects.create()
    GenerationJob.objects.create(project=project, kind="chat", status="running")
    response = client.post(f"/api/projects/{project.pk}/messages", {"content": "hi"}, format="json")
    assert response.status_code == 409
    assert response.json()["code"] == "job_in_progress"


def test_cancel_queued_job(client: APIClient) -> None:
    job = GenerationJob.objects.create(kind="agent", input={"slug": "ideas"})
    response = client.post(f"/api/jobs/{job.pk}/cancel").json()
    assert response["cancel_requested"] is True
    jobs.execute(job.pk)
    job.refresh_from_db()
    assert job.status == "cancelled"


def test_interrupted_jobs_are_recovered(db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    stale = GenerationJob.objects.create(kind="chat", status="running", boot_id="old")
    fresh = GenerationJob.objects.create(kind="chat", status="queued")
    monkeypatch.setattr(jobs, "_recovered", False)
    monkeypatch.setattr(jobs, "BOOT_TIME", fresh.created_at)
    GenerationJob.objects.filter(pk=stale.pk).update(
        created_at=fresh.created_at - timedelta(minutes=5)
    )
    assert jobs.recover_interrupted_jobs() == 1
    fresh.refresh_from_db()
    assert fresh.status == "queued"
    stale.refresh_from_db()
    assert stale.status == "failed"
    assert stale.error["kind"] == "interrupted"


def test_polling_after_restart_reports_interrupted_job(
    client: APIClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure_ai(key=KEY)
    project = Project.objects.create()
    stale = GenerationJob.objects.create(
        project=project, kind="chat", status="running", boot_id="old"
    )
    monkeypatch.setattr(jobs, "_recovered", False)
    monkeypatch.setattr(jobs, "BOOT_TIME", stale.created_at + timedelta(seconds=1))

    polled = client.get(f"/api/jobs/{stale.pk}").json()
    assert polled["status"] == "failed"
    assert polled["error"]["kind"] == "interrupted"
    assert client.get(f"/api/projects/{project.pk}").json()["jobs"][0]["status"] == "failed"


def test_production_reports_steps_and_attaches_video(
    client: APIClient,
    fake_providers: FakeRegistry,
    monkeypatch: pytest.MonkeyPatch,
    output_dir: Path,
) -> None:
    configure_ai(key=KEY)
    from engine.runtime import report
    from studio import handlers

    seen: dict[str, Any] = {}

    def fake_production(store: Any, request: Any, personality: str) -> dict[str, Any]:
        seen.update(task=request.task, personality=personality, format=request.short_format)
        for stage, agent in (("research", "research"), ("render", "renderer")):
            report("step", agent=agent, stage=stage, status="running", task_id="t")
            report("step", agent=agent, stage=stage, status="done", task_id="t")
        video = output_dir / "abcdef0123456789_tide-pools.mp4"
        video.write_bytes(b"\x00" * 64)
        asset = store.register_output(video, role="video", duration_seconds=12.0)
        return {"summary": "The cut is ready.", "video": asset, "limitations": []}

    monkeypatch.setattr(handlers, "run_production", fake_production)

    project = _project(client)
    response = client.post(
        f"/api/projects/{project['id']}/production",
        {"task": "A short about tide pools", "render_video": True, "short_format": "text_short"},
        format="json",
    )
    assert response.status_code == 202
    job = response.json()["job"]
    assert job["status"] == "succeeded", job["error"]
    assert seen == {
        "task": "A short about tide pools",
        "personality": "director",
        "format": "silent",
    }
    steps = [(e["agent"], e["data"].get("status")) for e in job["events"] if e["type"] == "step"]
    assert ("research", "running") in steps and ("renderer", "done") in steps
    labels = [e["message"] for e in job["events"] if e["type"] == "step"]
    assert "Timeline render verified" in labels
    media = job["result"]["media"]
    assert media[0]["display_name"] == "tide-pools.mp4"
    reply = Message.objects.filter(role="assistant").get()
    assert reply.persona == "director"
    assert reply.content == "The cut is ready."
    assert reply.attachments[0]["url"] == f"/api/media/{media[0]['id']}/file"


def test_only_registered_media_is_served(client: APIClient, output_dir: Path) -> None:
    (output_dir / "0123456789abcdef_mine.mp4").write_bytes(b"data")
    (output_dir / "0123456789abcdef_unregistered.mp4").write_bytes(b"data")
    asset = register_asset("0123456789abcdef_mine.mp4")
    assert asset is not None
    assert register_asset("../secrets.mp4") is None
    assert register_asset("0123456789abcdef_mine.mp4") == asset

    assert client.get(f"/api/media/{asset.pk}/file").status_code == 200
    assert client.get("/api/chat/videos/0123456789abcdef_mine.mp4").status_code == 200
    assert client.get("/api/chat/videos/0123456789abcdef_unregistered.mp4").status_code == 404
    assert client.get("/api/chat/videos/..%2F..%2Fmanage.py").status_code == 404


def test_media_supports_range_requests(client: APIClient, output_dir: Path) -> None:
    (output_dir / "0123456789abcdef_clip.mp4").write_bytes(b"0123456789")
    asset = register_asset("0123456789abcdef_clip.mp4")
    assert asset is not None
    partial = client.get(f"/api/media/{asset.pk}/file", HTTP_RANGE="bytes=2-5")
    assert partial.status_code == 206
    assert partial["Content-Range"] == "bytes 2-5/10"
    assert b"".join(partial.streaming_content) == b"2345"
    download = client.get(f"/api/media/{asset.pk}/file?download=1")
    assert download["Content-Disposition"].startswith("attachment;")
    assert 'filename="clip.mp4"' in download["Content-Disposition"]
    assert client.get(f"/api/media/{asset.pk}/file", HTTP_RANGE="bytes=50-").status_code == 416


def test_media_delete_removes_file(client: APIClient, output_dir: Path) -> None:
    path = output_dir / "0123456789abcdef_old.mp3"
    path.write_bytes(b"x")
    asset = register_asset(path.name)
    assert asset is not None
    assert client.delete(f"/api/media/{asset.pk}").status_code == 204
    assert not path.exists()
    assert not MediaAsset.objects.exists()


def test_legacy_import_is_additive_and_idempotent(client: APIClient, output_dir: Path) -> None:
    (output_dir / "feedface00000000_old-short.mp4").write_bytes(b"x")
    payload = {
        "chats": [
            {
                "id": "chat-1",
                "title": "Old chat",
                "updatedAt": 1700000000000,
                "messages": [
                    {"role": "user", "content": "Make a short"},
                    {
                        "role": "assistant",
                        "content": "Done!",
                        "attachments": [
                            {
                                "type": "video",
                                "url": "/api/chat/videos/feedface00000000_old-short.mp4",
                                "filename": "old-short.mp4",
                            }
                        ],
                    },
                ],
            },
            {"id": "chat-empty", "title": "Empty", "messages": []},
        ]
    }
    dry = client.post("/api/projects/import-legacy?dry_run=1", payload, format="json").json()
    assert dry["projects_created"] == 1 and not Project.objects.exists()

    first = client.post("/api/projects/import-legacy", payload, format="json").json()
    assert first["projects_created"] == 1
    assert first["projects_skipped"] == 1
    assert first["media_claimed"] == 1
    project = Project.objects.get(legacy_id="chat-1")
    assert project.title == "Old chat"
    attachment = project.messages.get(role="assistant").attachments[0]
    assert attachment["url"].startswith("/api/media/")

    second = client.post("/api/projects/import-legacy", payload, format="json").json()
    assert second["projects_created"] == 0
    assert Project.objects.count() == 1


def test_agent_registry_and_status(client: APIClient) -> None:
    agents = client.get("/api/agents/registry").json()
    orchestrator = agents["orchestrator"]
    assert [p["id"] for p in orchestrator["personalities"]] == ["director", "creative_partner"]
    assert "produce_video" in orchestrator["tools"]
    specialists = {s["id"]: s for s in agents["specialists"]}
    assert set(specialists) == {"research", "script", "visual", "ideas", "music_composer"}
    assert all(s["reports_to"] == "orchestrator" for s in specialists.values())
    assert "download_and_register_image" in specialists["visual"]["tools"]
    assert "report_visual_gap" in specialists["visual"]["tools"]
    assert specialists["visual"]["route"] == "production"
    assert {s["id"] for s in agents["services"]} == {"narration", "music", "renderer", "qc"}
    status = client.get("/api/agents/status").json()
    assert set(status["routes"]) == {"planner", "production"}
    assert {e["slug"] for e in status["endpoints"]} == {
        "ideas",
        "research",
        "script",
        "compose-music",
    }


def test_agent_job_validates_input_and_requires_config(client: APIClient) -> None:
    invalid = client.post("/api/agents/ideas", {"topic": ""}, format="json")
    assert invalid.status_code == 400
    blocked = client.post("/api/agents/ideas", {"topic": "Ocean facts"}, format="json")
    assert blocked.status_code == 409
    assert client.post("/api/agents/nope", {}, format="json").status_code == 404


def test_legacy_video_list(client: APIClient, output_dir: Path) -> None:
    (output_dir / "0123456789abcdef_a.mp4").write_bytes(b"x")
    register_asset("0123456789abcdef_a.mp4")
    videos = client.get("/api/chat/videos").json()
    assert videos[0]["filename"] == "a.mp4"
