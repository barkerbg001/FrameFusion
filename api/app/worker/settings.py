from arq.connections import RedisSettings

from app.core.config import REDIS_URL
from app.jobs.tasks import render_job


class WorkerSettings:
    functions = [render_job]
    redis_settings = RedisSettings.from_dsn(REDIS_URL)
