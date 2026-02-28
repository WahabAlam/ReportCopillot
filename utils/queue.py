from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Callable, Any


def _is_truthy(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class QueueResult:
    mode: str
    job_id: str | None = None
    error: str | None = None


def enqueue_job(
    *,
    background_tasks,
    worker_callable: Callable[..., Any],
    worker_path: str,
    worker_kwargs: dict,
) -> QueueResult:
    use_rq = _is_truthy(os.getenv("USE_RQ_QUEUE"), default=False)
    fallback_background = _is_truthy(os.getenv("RQ_FALLBACK_TO_BACKGROUND"), default=True)

    if use_rq:
        try:
            rq_job_id = _enqueue_rq(worker_path=worker_path, worker_kwargs=worker_kwargs)
            return QueueResult(mode="rq", job_id=rq_job_id)
        except Exception as e:
            if not fallback_background:
                return QueueResult(mode="rq_error", error=f"{type(e).__name__}: {e}")

    background_tasks.add_task(worker_callable, **worker_kwargs)
    return QueueResult(mode="background")


def _enqueue_rq(*, worker_path: str, worker_kwargs: dict) -> str:
    from rq import Queue
    from redis import from_url

    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    queue_name = os.getenv("RQ_QUEUE_NAME", "report_jobs")
    job_timeout = int(os.getenv("RQ_JOB_TIMEOUT_SECONDS", "1800"))
    result_ttl = int(os.getenv("RQ_RESULT_TTL_SECONDS", "86400"))

    conn = from_url(redis_url)
    q = Queue(queue_name, connection=conn)
    job = q.enqueue(
        worker_path,
        kwargs=worker_kwargs,
        job_timeout=job_timeout,
        result_ttl=result_ttl,
    )
    return str(job.id)
