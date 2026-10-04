"""Request protections for a single-user app without login.

Removing accounts means every request that reaches the API acts with the saved
credentials. Three layers keep other websites (and other machines) out:

* ``ALLOWED_HOSTS`` only lists localhost, which also blocks DNS-rebinding attacks.
* ``LocalRequestGuardMiddleware`` rejects API requests that a browser marks as
  cross-site, and unsafe requests whose ``Origin`` is not a configured frontend.
* ``CsrfOnlyAuthentication`` makes DRF enforce Django's CSRF token on every unsafe
  request, since there is no session authentication to do it.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.middleware.csrf import CsrfViewMiddleware
from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication
from rest_framework.request import Request

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
PUBLIC_PATHS = {"/api/chat/health", "/api/health"}


def _forbidden(message: str) -> JsonResponse:
    return JsonResponse({"detail": message, "code": "forbidden_origin"}, status=403)


def _origin_allowed(request: HttpRequest, origin: str) -> bool:
    if origin in settings.FRONTEND_ORIGINS:
        return True
    own = f"{request.scheme}://{request.get_host()}"
    return origin == own


class LocalRequestGuardMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if request.path.startswith("/api/") and request.path not in PUBLIC_PATHS:
            site = request.headers.get("Sec-Fetch-Site", "")
            if site == "cross-site":
                return _forbidden("Requests from other websites are not allowed.")
            origin = request.headers.get("Origin", "")
            if request.method not in SAFE_METHODS and origin and origin != "null":
                if not _origin_allowed(request, origin):
                    return _forbidden(
                        "This origin is not allowed. Add it to FRAMEFUSION_FRONTEND_ORIGINS "
                        "if it is your own local frontend."
                    )
            elif request.method not in SAFE_METHODS and origin == "null":
                return _forbidden("Requests from sandboxed or file:// pages are not allowed.")
        return self.get_response(request)


def _no_response(request: HttpRequest) -> HttpResponse:  # pragma: no cover - never called
    return HttpResponse()


class CsrfOnlyAuthentication(BaseAuthentication):
    """Enforce CSRF for unsafe methods; never identifies a user (there are none)."""

    def authenticate(self, request: Request) -> Any:
        check = CsrfViewMiddleware(_no_response)
        check.process_request(request._request)
        reason = check.process_view(request._request, None, (), {})  # type: ignore[arg-type]
        if reason:
            raise exceptions.PermissionDenied(
                "The security token is missing or expired. Reload the page and try again."
            )
        return None
