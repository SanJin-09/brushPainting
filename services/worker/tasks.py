from __future__ import annotations

import uuid
import os

from PIL import Image
from celery import shared_task
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from model_runtime.stylizer import ProgressCallback, inpaint_region, style_image
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


def _apply_job_progress(job: Job, *, progress_percent: int | None = None, progress_message: str | None = None) -> None:
    payload = dict(job.payload_json or {})
    if progress_percent is not None:
        payload["progress_percent"] = max(0, min(100, int(progress_percent)))
    if progress_message is not None:
        payload["progress_message"] = progress_message
    job.payload_json = payload


def _job_update(
    db,
    job: Job,
    status: JobStatus,
    error: str | None = None,
    *,
    progress_percent: int | None = None,
    progress_message: str | None = None,
) -> None:
    job.status = status.value
    job.error_message = error
    _apply_job_progress(job, progress_percent=progress_percent, progress_message=progress_message)
    db.add(job)


def _make_progress_callback(
    db,
    job: Job,
    *,
    start_percent: int,
    end_percent: int,
    default_message: str,
) -> ProgressCallback:
    last_percent = max(start_percent, job.progress_percent or start_percent)
    last_step = 0

    def _progress_callback(step_index: int, total_steps: int, message: str) -> None:
        nonlocal last_percent, last_step
        if total_steps <= 0:
            return

        ratio = min(max(step_index, 0), total_steps) / total_steps
        percent = int(round(start_percent + (end_percent - start_percent) * ratio))
        min_step_gap = max(1, total_steps // 10)
        if step_index < total_steps and percent <= last_percent:
            return
        if step_index < total_steps and step_index - last_step < min_step_gap and percent - last_percent < 3:
            return

        _job_update(
            db,
            job,
            JobStatus.RUNNING,
            progress_percent=percent,
            progress_message=message or default_message,
        )
        db.commit()
        last_percent = percent
        last_step = step_index

    return _progress_callback


def _open_image(url: str) -> Image.Image:
    path = storage.url_to_path(url)
    return Image.open(path)


def _version_path(version_id: str) -> str:
    return f"versions/{version_id}.png"


def _current_model_backend() -> str:
    return os.getenv("MODEL_BACKEND", settings.model_backend).strip().lower()


def _render_params_payload(session_obj: Session, seed: int) -> dict[str, object]:
    backend = _current_model_backend()
    if backend == "qwen_image":
        from model_runtime.qwen_image_backend import resolve_qwen_runtime_config

        runtime_config = resolve_qwen_runtime_config()
        return {
            "style_id": session_obj.style_id,
            "seed": seed,
            "steps": runtime_config["steps"],
            "true_cfg_scale": runtime_config["true_cfg_scale"],
            "guidance_scale": runtime_config["guidance_scale"],
            "model_backend": backend,
        }
    return {
        "style_id": session_obj.style_id,
        "seed": seed,
        "steps": settings.z_image_steps,
        "cfg": settings.z_image_cfg,
        "size": settings.z_image_size,
        "img2img_strength": settings.z_image_img2img_strength,
        "model_backend": backend,
    }


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
            _job_update(
                db,
                job,
                JobStatus.RUNNING,
                progress_percent=10,
                progress_message="正在准备整图任务",
            )
            db.commit()

            if not session_obj.style_id:
                raise RuntimeError("style is not locked")

            _job_update(
                db,
                job,
                JobStatus.RUNNING,
                progress_percent=18,
                progress_message="正在读取原图",
            )
            db.commit()

            with _open_image(session_obj.source_image_url) as source:
                _job_update(
                    db,
                    job,
                    JobStatus.RUNNING,
                    progress_percent=28,
                    progress_message="正在生成整图",
                )
                db.commit()
                rendered = style_image(
                    source,
                    seed=seed,
                    controlnet_weight=1.0,
                    progress_callback=_make_progress_callback(
                        db,
                        job,
                        start_percent=28,
                        end_percent=86,
                        default_message="正在生成整图",
                    ),
                )

            _job_update(
                db,
                job,
                JobStatus.RUNNING,
                progress_percent=92,
                progress_message="正在保存整图结果",
            )
            db.commit()

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
                    params_hash=params_hash(_render_params_payload(session_obj, seed)),
                    is_current=should_be_current,
                )
            )

            session_obj.seed = seed
            session_obj.status = SessionStatus.REVIEWING.value
            _job_update(
                db,
                job,
                JobStatus.SUCCEEDED,
                progress_percent=100,
                progress_message="整图生成完成",
            )
            db.commit()
        except Exception as exc:
            _job_update(
                db,
                job,
                JobStatus.FAILED,
                str(exc),
                progress_message="整图生成失败",
            )
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
            _job_update(
                db,
                job,
                JobStatus.RUNNING,
                progress_percent=10,
                progress_message="正在准备局部重绘",
            )
            db.commit()

            current_version = current_version_or_raise(session_obj)
            _job_update(
                db,
                job,
                JobStatus.RUNNING,
                progress_percent=18,
                progress_message="正在校验选区",
            )
            db.commit()
            with _open_image(session_obj.source_image_url) as source, _open_image(current_version.image_url) as current_image:
                mask = decode_and_validate_mask(mask_rle, image_size=current_image.size)
                validate_bbox(bbox_x, bbox_y, bbox_w, bbox_h, image_size=current_image.size)
                _job_update(
                    db,
                    job,
                    JobStatus.RUNNING,
                    progress_percent=28,
                    progress_message="正在生成局部候选",
                )
                db.commit()
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
                    progress_callback=_make_progress_callback(
                        db,
                        job,
                        start_percent=28,
                        end_percent=86,
                        default_message="正在生成局部候选",
                    ),
                )

            _job_update(
                db,
                job,
                JobStatus.RUNNING,
                progress_percent=92,
                progress_message="正在保存局部候选",
            )
            db.commit()

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
            _job_update(
                db,
                job,
                JobStatus.SUCCEEDED,
                progress_percent=100,
                progress_message="局部候选生成完成",
            )
            db.commit()
        except Exception as exc:
            _job_update(
                db,
                job,
                JobStatus.FAILED,
                str(exc),
                progress_message="局部候选生成失败",
            )
            session_obj.status = SessionStatus.FAILED.value
            db.commit()
            raise
