import asyncio

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from starlette.background import BackgroundTasks

from app.core.config import JOB_QUEUE_BACKEND, REDIS_URL
from app.jobs.tasks import run_render_job

_arq_pool: ArqRedis | None = None


async def get_arq_pool() -> ArqRedis:
    global _arq_pool
    if _arq_pool is None:
        _arq_pool = await create_pool(RedisSettings.from_dsn(REDIS_URL))
    return _arq_pool


async def close_arq_pool() -> None:
    global _arq_pool
    if _arq_pool is not None:
        await _arq_pool.close()
        _arq_pool = None


async def schedule_render_job(
    job_id: str,
    background_tasks: BackgroundTasks | None = None,
) -> None:
    if JOB_QUEUE_BACKEND == "inline":
        if background_tasks is not None:
            background_tasks.add_task(run_render_job, job_id)
            return
        asyncio.create_task(run_render_job(job_id))
        return

    if JOB_QUEUE_BACKEND == "arq":
        pool = await get_arq_pool()
        await pool.enqueue_job("render_job", job_id)
        return

    raise RuntimeError(f"Unsupported JOB_QUEUE_BACKEND: {JOB_QUEUE_BACKEND}")
