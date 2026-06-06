from __future__ import annotations

import uuid
from typing import Any

from redis import Redis
from rq import Queue
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from services.api.app.core.config import get_settings
from services.api.app.models.entities import ImageAsset, Job
from services.api.app.models.enums import ImageStatus, JobStatus
from services.api.app.services.errors import ConflictError, ServiceUnavailableError

settings = get_settings()


def create_job(
    db: Session,
    *,
    job_type: str,
    image: ImageAsset,
    payload: dict[str, Any],
) -> Job:
    job = Job(
        id=str(uuid.uuid4()),
        type=job_type,
        batch_id=image.batch_id,
        image_id=image.id,
        input_payload=payload,
        status=JobStatus.QUEUED.value,
        progress=0,
        progress_message="排队中",
    )
    image.status = ImageStatus.QUEUED.value
    db.add(job)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("该图片已有排队中或运行中的任务") from exc
    db.refresh(job)
    return job


def dispatch_job(job_id: str) -> None:
    try:
        queue = Queue(settings.rq_queue_name, connection=Redis.from_url(settings.redis_url))
        if queue.count >= settings.rq_max_queued_jobs:
            raise ServiceUnavailableError("GPU 任务队列已满，请稍后重试")
        queue.enqueue(
            "services.worker.tasks.run_generation",
            job_id,
            job_id=job_id,
            job_timeout="4h",
            result_ttl=86400,
            failure_ttl=86400,
        )
    except ServiceUnavailableError:
        raise
    except Exception as exc:
        raise ServiceUnavailableError("无法连接 GPU 任务队列") from exc
