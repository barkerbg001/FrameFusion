"""Django settings for the FrameFusion API.

FrameFusion is a single-user application meant to run on your own machine. There
is no login: anyone who can reach the API can use every saved credential, so the
server only accepts local hosts and origins unless FRAMEFUSION_ALLOW_REMOTE is set.

All secrets and deployment-specific values come from the environment
(``api/.env`` is loaded for local development). See ``api/.env.example``.
"""

import os
from pathlib import Path
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


def env_int(name: str, default: int) -> int:
    value = os.environ.get(name, "").strip()
    return int(value) if value else default


def env_path(name: str, default: Path) -> Path:
    value = os.environ.get(name, "").strip()
    path = Path(value) if value else default
    if not path.is_absolute():
        path = BASE_DIR / path
    return path.resolve()


DEBUG = env_bool("DJANGO_DEBUG", False)

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "").strip()
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "framefusion-insecure-dev-key-do-not-use-in-production"
    else:
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY is not set. Run `npm run setup` or copy api/.env.example "
            "to api/.env and fill in the values."
        )

# --- Local-only access -------------------------------------------------------------------
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}
FRAMEFUSION_ALLOW_REMOTE = env_bool("FRAMEFUSION_ALLOW_REMOTE", False)

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost,[::1]")

FRONTEND_ORIGINS = env_list(
    "FRAMEFUSION_FRONTEND_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173"
)

_remote_hosts = [host for host in ALLOWED_HOSTS if host not in LOCAL_HOSTS]
_remote_origins = [
    origin for origin in FRONTEND_ORIGINS if (urlsplit(origin).hostname or "") not in LOCAL_HOSTS
]
if (_remote_hosts or _remote_origins) and not FRAMEFUSION_ALLOW_REMOTE:
    raise ImproperlyConfigured(
        "FrameFusion has no login, so it only serves localhost by default. "
        f"Non-local hosts/origins configured: {', '.join(_remote_hosts + _remote_origins)}. "
        "Remove them, or set FRAMEFUSION_ALLOW_REMOTE=true only if the server is protected "
        "by your own authentication (see SECURITY.md)."
    )

CSRF_TRUSTED_ORIGINS = FRONTEND_ORIGINS
CORS_ALLOWED_ORIGINS = FRONTEND_ORIGINS
CORS_ALLOW_CREDENTIALS = True

INSTALLED_APPS = [
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "providers",
    "studio",
    "tools",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "common.security.LocalRequestGuardMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# --- Database (SQLite) -----------------------------------------------------------------
# WAL lets the API read while a background job writes; IMMEDIATE transactions take the
# write lock up front so concurrent writers wait (busy timeout) instead of failing.
DATABASE_PATH = env_path("FRAMEFUSION_DB_PATH", BASE_DIR / "var" / "framefusion.sqlite3")
DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": DATABASE_PATH,
        "OPTIONS": {
            "timeout": 30,
            "transaction_mode": "IMMEDIATE",
            "init_command": (
                "PRAGMA journal_mode=WAL;PRAGMA synchronous=NORMAL;"
                "PRAGMA foreign_keys=ON;PRAGMA busy_timeout=30000"
            ),
        },
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = env_path("FRAMEFUSION_STATIC_ROOT", BASE_DIR / "var" / "static")
STATIC_ROOT.mkdir(parents=True, exist_ok=True)

# --- CSRF and cookies --------------------------------------------------------------------
# There are no sessions. The CSRF cookie plus the origin guard in common.security stop
# other websites open in the same browser from driving the local API.
CSRF_COOKIE_HTTPONLY = False  # the SPA reads it to send X-CSRFToken
CSRF_COOKIE_SAMESITE = "Strict"
CSRF_FAILURE_VIEW = "common.http.csrf_failure"
CSRF_COOKIE_SECURE = env_bool("DJANGO_SECURE_COOKIES", False)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# --- Uploads ----------------------------------------------------------------------------
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
FRAMEFUSION_MAX_UPLOAD_BYTES = env_int("FRAMEFUSION_MAX_UPLOAD_MB", 200) * 1024 * 1024
FRAMEFUSION_UPLOAD_DIR = env_path("FRAMEFUSION_UPLOAD_DIR", BASE_DIR / "var" / "uploads")
# --- REST framework ---------------------------------------------------------------------
REST_FRAMEWORK = {
    # No accounts: this "authentication" only enforces CSRF on unsafe methods.
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "common.security.CsrfOnlyAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.AllowAny",
    ],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.MultiPartParser",
        "rest_framework.parsers.FormParser",
    ],
    "EXCEPTION_HANDLER": "common.http.exception_handler",
    "UNAUTHENTICATED_USER": None,
    "UNAUTHENTICATED_TOKEN": None,
}

# --- FrameFusion ------------------------------------------------------------------------
FRAMEFUSION_OUTPUT_DIR = env_path("FRAMEFUSION_OUTPUT_DIR", BASE_DIR / "generated")
os.environ["FRAMEFUSION_OUTPUT_DIR"] = str(FRAMEFUSION_OUTPUT_DIR)

# Fernet key(s) for encrypting provider API keys at rest. Comma-separate to rotate:
# the first key encrypts, all keys decrypt. Must never be stored in the database.
FRAMEFUSION_ENCRYPTION_KEYS = env_list("FRAMEFUSION_ENCRYPTION_KEY")

FRAMEFUSION_JOB_WORKERS = max(1, env_int("FRAMEFUSION_JOB_WORKERS", 2))
FRAMEFUSION_JOBS_EAGER = env_bool("FRAMEFUSION_JOBS_EAGER", False)

FRAMEFUSION_LLM_TIMEOUT_SECONDS = env_int("FRAMEFUSION_LLM_TIMEOUT_SECONDS", 120)
FRAMEFUSION_LLM_MAX_RETRIES = env_int("FRAMEFUSION_LLM_MAX_RETRIES", 2)
FRAMEFUSION_DISCOVERY_TIMEOUT_SECONDS = env_int("FRAMEFUSION_DISCOVERY_TIMEOUT_SECONDS", 20)

# Fallback model lists shown when live model discovery is unavailable.
FRAMEFUSION_FALLBACK_MODELS = {
    "openrouter": env_list(
        "FRAMEFUSION_OPENROUTER_FALLBACK_MODELS",
        "openai/gpt-4o-mini,anthropic/claude-sonnet-4.5,google/gemini-2.5-flash",
    ),
    "gemini": env_list(
        "FRAMEFUSION_GEMINI_FALLBACK_MODELS", "gemini-flash-latest,gemini-pro-latest"
    ),
    "anthropic": env_list(
        "FRAMEFUSION_ANTHROPIC_FALLBACK_MODELS", "claude-sonnet-4-5,claude-haiku-4-5"
    ),
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django.db.backends": {"level": "WARNING"},
        "httpx": {"level": "WARNING"},
        "google_genai": {"level": "WARNING"},
        "anthropic": {"level": "WARNING"},
        "openai": {"level": "WARNING"},
    },
}
