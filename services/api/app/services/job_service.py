from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from services.api.app.models.entities import Job
from services.api.app.models.enums import JobStatus
from services.worker.celery_app import celery_app


def create_job(
    db: Session,
    *,
    job_type: str,
    session_id: str | None,
    payload: dict[str, Any] | None = None,
) -> Job:
    job_payload = dict(payload or {})
    job_payload.setdefault("progress_percent", 0)
    job_payload.setdefault("progress_message", "排队中")
    job = Job(
        id=str(uuid.uuid4()),
        type=job_type,
        session_id=session_id,
        payload_json=job_payload,
        status=JobStatus.QUEUED.value,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def dispatch_job(task_name: str, *args: Any) -> None:
    celery_app.send_task(task_name, args=list(args))
