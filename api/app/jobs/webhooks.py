from __future__ import annotations

import asyncio
import logging

import httpx

from app.jobs import store
from app.jobs.models import JobStatusResponse

logger = logging.getLogger(__name__)


async def dispatch_job_webhook(job_id: str) -> None:
    job = store.get_job(job_id)
    if job is None or not job.webhook_url:
        return

    payload = JobStatusResponse(
        id=job.id,
        job_type=job.job_type,
        status=job.status,
        progress=job.progress,
        created_at=job.created_at,
        updated_at=job.updated_at,
        output_filename=job.output_filename,
        error=job.error,
    )

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                job.webhook_url,
                json=payload.model_dump(mode="json"),
            )
            response.raise_for_status()
    except Exception:
        logger.exception("Webhook delivery failed for job %s", job_id)


def schedule_job_webhook(job_id: str) -> None:
    asyncio.create_task(dispatch_job_webhook(job_id))
