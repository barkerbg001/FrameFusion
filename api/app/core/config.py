from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# api/ directory (parent of app/)
API_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(API_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    uploads_dir: Path = Field(default=API_ROOT / "uploads", alias="UPLOADS_DIR")
    output_dir: Path = Field(default=API_ROOT / "output", alias="OUTPUT_DIR")
    jobs_dir: Path = Field(default=API_ROOT / "jobs", alias="JOBS_DIR")
    jobs_db_path: Path = Field(default=API_ROOT / "jobs.db", alias="JOBS_DB_PATH")
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    job_queue_backend: str = Field(default="inline", alias="JOB_QUEUE_BACKEND")
    cors_origins: str = Field(default="*", alias="CORS_ORIGINS")
    max_image_count: int = Field(default=10, alias="MAX_IMAGE_COUNT")
    max_image_size_bytes: int = Field(
        default=20 * 1024 * 1024,
        alias="MAX_IMAGE_SIZE_BYTES",
    )
    max_audio_size_bytes: int = Field(
        default=100 * 1024 * 1024,
        alias="MAX_AUDIO_SIZE_BYTES",
    )
    rate_limit_enabled: bool = Field(default=True, alias="RATE_LIMIT_ENABLED")
    rate_limit_generate: str = Field(default="6/hour", alias="RATE_LIMIT_GENERATE")
    rate_limit_job_download: str = Field(default="30/hour", alias="RATE_LIMIT_JOB_DOWNLOAD")
    rate_limit_job_status: str = Field(default="120/minute", alias="RATE_LIMIT_JOB_STATUS")
    cleanup_ttl_hours: int = Field(default=168, alias="CLEANUP_TTL_HOURS")
    cleanup_interval_seconds: int = Field(default=3600, alias="CLEANUP_INTERVAL_SECONDS")
    storage_backend: str = Field(default="local", alias="STORAGE_BACKEND")
    s3_endpoint_url: str = Field(default="", alias="S3_ENDPOINT_URL")
    s3_bucket: str = Field(default="", alias="S3_BUCKET")
    s3_access_key_id: str = Field(default="", alias="S3_ACCESS_KEY_ID")
    s3_secret_access_key: str = Field(default="", alias="S3_SECRET_ACCESS_KEY")
    s3_region: str = Field(default="us-east-1", alias="S3_REGION")
    e2e_fast_render: bool = Field(default=False, alias="E2E_FAST_RENDER")

    @field_validator(
        "uploads_dir",
        "output_dir",
        "jobs_dir",
        "jobs_db_path",
        mode="before",
    )
    @classmethod
    def expand_path(cls, value: object) -> object:
        if isinstance(value, str):
            return Path(value)
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        origins = [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]
        return origins or ["*"]


settings = Settings()

UPLOADS_DIR = settings.uploads_dir
OUTPUT_DIR = settings.output_dir
JOBS_DIR = settings.jobs_dir
JOBS_DB_PATH = settings.jobs_db_path
REDIS_URL = settings.redis_url
JOB_QUEUE_BACKEND = settings.job_queue_backend
CORS_ORIGINS = settings.cors_origin_list
MAX_IMAGE_COUNT = settings.max_image_count
MAX_IMAGE_SIZE_BYTES = settings.max_image_size_bytes
MAX_AUDIO_SIZE_BYTES = settings.max_audio_size_bytes
RATE_LIMIT_ENABLED = settings.rate_limit_enabled
RATE_LIMIT_GENERATE = settings.rate_limit_generate
RATE_LIMIT_JOB_DOWNLOAD = settings.rate_limit_job_download
RATE_LIMIT_JOB_STATUS = settings.rate_limit_job_status
CLEANUP_TTL_SECONDS = settings.cleanup_ttl_hours * 3600
CLEANUP_INTERVAL_SECONDS = settings.cleanup_interval_seconds
STORAGE_BACKEND = settings.storage_backend
S3_ENDPOINT_URL = settings.s3_endpoint_url
S3_BUCKET = settings.s3_bucket
S3_ACCESS_KEY_ID = settings.s3_access_key_id
S3_SECRET_ACCESS_KEY = settings.s3_secret_access_key
S3_REGION = settings.s3_region
E2E_FAST_RENDER = settings.e2e_fast_render


def ensure_directories() -> None:
    """Create runtime data directories if they do not exist."""
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
