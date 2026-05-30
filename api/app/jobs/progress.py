import time
from contextvars import ContextVar, Token

from app.jobs import store

job_id_ctx: ContextVar[str | None] = ContextVar("render_job_id", default=None)
encode_progress_range_ctx: ContextVar[tuple[float, float]] = ContextVar(
    "encode_progress_range",
    default=(5.0, 95.0),
)

_last_progress_write: dict[str, tuple[float, float]] = {}


def bind_render_job(job_id: str) -> Token[str | None]:
    return job_id_ctx.set(job_id)


def unbind_render_job(token: Token[str | None]) -> None:
    job_id = job_id_ctx.get()
    job_id_ctx.reset(token)
    if job_id is not None:
        _last_progress_write.pop(job_id, None)


def set_encode_progress_range(start: float, end: float) -> Token[tuple[float, float]]:
    return encode_progress_range_ctx.set((start, end))


def reset_encode_progress_range(token: Token[tuple[float, float]]) -> None:
    encode_progress_range_ctx.reset(token)


def get_encode_progress_range() -> tuple[float, float]:
    return encode_progress_range_ctx.get()


def update_render_progress(progress: float) -> None:
    job_id = job_id_ctx.get()
    if job_id is None:
        return

    clamped = max(0.0, min(100.0, progress))
    now = time.time()
    previous = _last_progress_write.get(job_id)
    if previous is not None:
        elapsed = now - previous[0]
        delta = abs(clamped - previous[1])
        if clamped < 100 and elapsed < 0.5 and delta < 1.0:
            return

    store.update_job(job_id, progress=clamped)
    _last_progress_write[job_id] = (now, clamped)


def clear_render_progress_state(job_id: str) -> None:
    _last_progress_write.pop(job_id, None)
