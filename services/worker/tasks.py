from __future__ import annotations

import uuid

from PIL import Image
from celery import shared_task
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from model_runtime.stylizer import inpaint_region, style_image
from services.api.app.core.config import get_settings
from services.api.app.db.database import SessionLocal
from services.api.app.models.entities import ImageVersion, Job, Session
from services.api.app.models.enums import ImageVersionKind, JobStatus, SessionStatus
from services.api.app.services.session_service import (
    current_version_or_raise,
    decode_and_validate_mask,
    params_hash,
    validate_bbox,
)
from services.api.app.services.storage import LocalMediaStorage

settings = get_settings()
storage = LocalMediaStorage()


def _job_update(db, job: Job, status: JobStatus, error: str | None = None) -> None:
    job.status = status.value
    job.error_message = error
    db.add(job)


def _open_image(url: str) -> Image.Image:
    path = storage.url_to_path(url)
    return Image.open(path)


def _version_path(version_id: str) -> str:
    return f"versions/{version_id}.png"


@shared_task(name="services.worker.tasks.render_full", bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 2})
def render_full(self, job_id: str, session_id: str, seed: int):
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        session_obj = db.execute(
            select(Session)
            .where(Session.id == session_id)
            .options(selectinload(Session.versions))
        ).scalar_one_or_none()

        if not job or not session_obj:
            return

        try:
            _job_update(db, job, JobStatus.RUNNING)
            db.commit()

            if not session_obj.style_id:
                raise RuntimeError("style is not locked")

            with _open_image(session_obj.source_image_url) as source:
                rendered = style_image(
                    source,
                    seed=seed,
                    controlnet_weight=1.0,
                )

            version_id = str(uuid.uuid4())
            image_url = storage.save_image(session_obj.id, _version_path(version_id), rendered)
            should_be_current = session_obj.current_version is None
            db.add(
                ImageVersion(
                    id=version_id,
                    session_id=session_obj.id,
                    parent_version_id=session_obj.current_version_id,
                    kind=ImageVersionKind.FULL_RENDER.value,
                    image_url=image_url,
                    seed=seed,
                    params_hash=params_hash(
                        {
                            "style_id": session_obj.style_id,
                            "seed": seed,
                            "steps": settings.z_image_steps,
                            "cfg": settings.z_image_cfg,
                            "size": settings.z_image_size,
                            "img2img_strength": settings.z_image_img2img_strength,
                            "model_backend": settings.model_backend,
                        }
                    ),
                    is_current=should_be_current,
                )
            )

            session_obj.seed = seed
            session_obj.status = SessionStatus.REVIEWING.value
            _job_update(db, job, JobStatus.SUCCEEDED)
            db.commit()
        except Exception as exc:
            _job_update(db, job, JobStatus.FAILED, str(exc))
            session_obj.status = SessionStatus.FAILED.value
            db.commit()
            raise


@shared_task(name="services.worker.tasks.edit_mask", bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 2})
def edit_mask(
    self,
    job_id: str,
    session_id: str,
    seed: int,
    mask_rle: str,
    bbox_x: int,
    bbox_y: int,
    bbox_w: int,
    bbox_h: int,
    prompt_override: str | None,
):
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        session_obj = db.execute(
            select(Session)
            .where(Session.id == session_id)
            .options(selectinload(Session.versions))
        ).scalar_one_or_none()

        if not job or not session_obj:
            return

        try:
            _job_update(db, job, JobStatus.RUNNING)
            db.commit()

            current_version = current_version_or_raise(session_obj)
            with _open_image(session_obj.source_image_url) as source, _open_image(current_version.image_url) as current_image:
                mask = decode_and_validate_mask(mask_rle, image_size=current_image.size)
                validate_bbox(bbox_x, bbox_y, bbox_w, bbox_h, image_size=current_image.size)
                edited = inpaint_region(
                    current_image,
                    source,
                    mask,
                    bbox_x=bbox_x,
                    bbox_y=bbox_y,
                    bbox_w=bbox_w,
                    bbox_h=bbox_h,
                    seed=seed,
                    controlnet_weight=1.0,
                    context_pad=settings.inpaint_context_pad,
                    mask_feather=settings.inpaint_mask_feather,
                    prompt_override=prompt_override,
                )

            version_id = str(uuid.uuid4())
            image_url = storage.save_image(session_obj.id, _version_path(version_id), edited)
            db.add(
                ImageVersion(
                    id=version_id,
                    session_id=session_obj.id,
                    parent_version_id=current_version.id,
                    kind=ImageVersionKind.LOCAL_EDIT.value,
                    image_url=image_url,
                    seed=seed,
                    params_hash=params_hash(
                        {
                            "style_id": session_obj.style_id,
                            "seed": seed,
                            "steps": settings.z_image_steps,
                            "cfg": settings.z_image_cfg,
                            "size": settings.z_image_size,
                            "context_pad": settings.inpaint_context_pad,
                            "mask_feather": settings.inpaint_mask_feather,
                            "inpaint_strength": settings.z_image_inpaint_strength,
                            "prompt_override": prompt_override or "",
                            "model_backend": settings.model_backend,
                        }
                    ),
                    is_current=False,
                    prompt_override=prompt_override,
                    mask_rle=mask_rle,
                    bbox_x=bbox_x,
                    bbox_y=bbox_y,
                    bbox_w=bbox_w,
                    bbox_h=bbox_h,
                )
            )

            session_obj.seed = seed
            session_obj.status = SessionStatus.REVIEWING.value
            _job_update(db, job, JobStatus.SUCCEEDED)
            db.commit()
        except Exception as exc:
            _job_update(db, job, JobStatus.FAILED, str(exc))
            session_obj.status = SessionStatus.FAILED.value
            db.commit()
            raise
