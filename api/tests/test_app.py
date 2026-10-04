"""Single-user app: bootstrap, request protections, onboarding."""

from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


def test_app_bootstrap_sets_csrf_cookie_and_reports_state(csrf_client: APIClient) -> None:
    response = csrf_client.get("/api/app")
    assert response.status_code == 200
    assert "csrftoken" in response.cookies
    body = response.json()
    assert body["theme"] == "system"
    assert body["onboarding"]["completed"] is False
    assert body["onboarding"]["step"] == "welcome"
    assert body["readiness"]["planner"]["ready"] is False
    assert body["integrations"]["pexels"]["configured"] is False
    assert body["pending_import_choices"] == 0


def test_no_account_endpoints_exist(client: APIClient) -> None:
    for path in ("/api/auth/session", "/api/auth/login", "/api/auth/register", "/admin/"):
        assert client.get(path).status_code == 404


def test_writes_require_csrf_token(csrf_client: APIClient) -> None:
    blocked = csrf_client.post("/api/projects", {}, format="json")
    assert blocked.status_code == 403
    assert "security token" in blocked.json()["detail"]

    token = csrf_client.get("/api/app").cookies["csrftoken"].value
    allowed = csrf_client.post("/api/projects", {}, format="json", HTTP_X_CSRFTOKEN=token)
    assert allowed.status_code == 201


def test_cross_site_requests_are_rejected(client: APIClient) -> None:
    cross = client.get("/api/projects", HTTP_SEC_FETCH_SITE="cross-site")
    assert cross.status_code == 403
    assert cross.json()["code"] == "forbidden_origin"
    evil = client.post("/api/projects", {}, format="json", HTTP_ORIGIN="https://evil.example")
    assert evil.status_code == 403
    null = client.post("/api/projects", {}, format="json", HTTP_ORIGIN="null")
    assert null.status_code == 403
    ok = client.post("/api/projects", {}, format="json", HTTP_ORIGIN="http://localhost:5173")
    assert ok.status_code == 201
    same_origin = client.get("/api/projects", HTTP_SEC_FETCH_SITE="same-origin")
    assert same_origin.status_code == 200


def test_non_local_hosts_require_explicit_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    import config.settings as settings_module

    monkeypatch.setenv("DJANGO_ALLOWED_HOSTS", "framefusion.example.com")
    monkeypatch.delenv("FRAMEFUSION_ALLOW_REMOTE", raising=False)
    try:
        with pytest.raises(ImproperlyConfigured, match="SECURITY.md"):
            importlib.reload(settings_module)
        monkeypatch.setenv("FRAMEFUSION_ALLOW_REMOTE", "true")
        importlib.reload(settings_module)
        assert "framefusion.example.com" in settings_module.ALLOWED_HOSTS
    finally:
        monkeypatch.delenv("DJANGO_ALLOWED_HOSTS", raising=False)
        monkeypatch.delenv("FRAMEFUSION_ALLOW_REMOTE", raising=False)
        importlib.reload(settings_module)


def test_theme_is_saved(client: APIClient) -> None:
    assert client.put("/api/settings/appearance", {"theme": "dark"}, format="json").json() == {
        "theme": "dark"
    }
    assert client.get("/api/app").json()["theme"] == "dark"
    assert (
        client.put("/api/settings/appearance", {"theme": "neon"}, format="json").status_code == 400
    )


def test_onboarding_progress_persists_skips_completes_and_restarts(client: APIClient) -> None:
    def put(**data: Any) -> dict[str, Any]:
        response = client.put("/api/settings/onboarding", data, format="json")
        assert response.status_code == 200
        return response.json()

    assert put(step="providers")["step"] == "providers"
    assert client.get("/api/app").json()["onboarding"]["step"] == "providers"

    skipped = put(skip="media", step="appearance")
    assert skipped["skipped"] == ["media"]
    assert skipped["step"] == "appearance"

    revisited = put(step="media")
    assert revisited["skipped"] == []

    done = put(complete=True)
    assert done["completed"] is True and done["completed_at"]
    assert client.get("/api/app").json()["onboarding"]["completed"] is True

    restarted = put(restart=True)
    assert restarted == {
        "steps": [
            "welcome",
            "providers",
            "models",
            "narration",
            "media",
            "appearance",
            "review",
        ],
        "step": "welcome",
        "skipped": [],
        "completed": False,
        "completed_at": None,
    }
    assert (
        client.put("/api/settings/onboarding", {"step": "bogus"}, format="json").status_code == 400
    )
