from __future__ import annotations

import hashlib
import uuid
from typing import Any

import numpy as np
from PIL import Image
from celery import shared_task
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from model_runtime.composer import Layer, compose_with_seam_refine
from model_runtime.rle import decode_mask_rle
from model_runtime.segmenter import segment_image
from model_runtime.stylizer import style_crop
from services.api.app.core.config import get_settings
from services.api.app.db.database import SessionLocal
from services.api.app.models.entities import ComposeResult, Crop, CropVersion, Job, Session
from services.api.app.models.enums import CropStatus, JobStatus, SessionStatus
from services.api.app.services.storage import LocalMediaStorage

settings = get_settings()
storage = LocalMediaStorage()


def _job_update(db, job: Job, status: JobStatus, error: str | None = None) -> None:
    job.status = status.value
    job.error_message = error
    db.add(job)


def _hash_params(payload: dict[str, Any]) -> str:
    raw = str(sorted(payload.items())).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]


def _open_image(url: str) -> Image.Image:
    path = storage.url_to_path(url)
    return Image.open(path)


def _crop_with_mask(source: Image.Image, crop: Crop) -> tuple[Image.Image, np.ndarray]:
    mask_full = decode_mask_rle(crop.mask_rle)
    x, y, w, h = crop.bbox_x, crop.bbox_y, crop.bbox_w, crop.bbox_h

    crop_rgb = source.convert("RGB").crop((x, y, x + w, y + h))
    crop_mask = mask_full[y : y + h, x : x + w].astype(np.uint8)
    return crop_rgb, crop_mask


@shared_task(name="services.worker.tasks.segment_session", bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 2})
def segment_session(self, job_id: str, session_id: str, seed: int, crop_count: int):
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        session_obj = db.get(Session, session_id)
        if not job or not session_obj:
            return

        try:
            _job_update(db, job, JobStatus.RUNNING)
            db.commit()

            for crop in list(session_obj.crops):
                db.delete(crop)
            db.flush()

            source = _open_image(session_obj.source_image_url)
            segments = segment_image(
                source,
                seed=seed,
                crop_count=crop_count,
                min_area_ratio=settings.min_area_ratio,
                max_area_ratio=settings.max_area_ratio,
                max_overlap_iou=settings.max_overlap_iou,
            )

            for seg in segments:
                db.add(
                    Crop(
                        id=str(uuid.uuid4()),
                        session_id=session_obj.id,
                        bbox_x=seg.bbox_x,
                        bbox_y=seg.bbox_y,
                        bbox_w=seg.bbox_w,
                        bbox_h=seg.bbox_h,
                        mask_rle=seg.mask_rle,
                        status=CropStatus.PENDING.value,
                    )
                )

            session_obj.seed = seed
            session_obj.status = SessionStatus.SEGMENTED.value if not session_obj.style_id else SessionStatus.STYLE_LOCKED.value
            _job_update(db, job, JobStatus.SUCCEEDED)
            db.commit()
        except Exception as exc:
            _job_update(db, job, JobStatus.FAILED, str(exc))
            session_obj.status = SessionStatus.FAILED.value
            db.commit()
            raise


@shared_task(name="services.worker.tasks.generate_all_crops", bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 2})
def generate_all_crops(self, job_id: str, session_id: str):
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        session_obj = db.execute(
            select(Session)
            .where(Session.id == session_id)
            .options(selectinload(Session.crops).selectinload(Crop.versions))
        ).scalar_one_or_none()

        if not job or not session_obj:
            return

        try:
            _job_update(db, job, JobStatus.RUNNING)
            db.commit()

            source = _open_image(session_obj.source_image_url)
            if not session_obj.style_id:
                raise RuntimeError("style is not locked")

            for idx, crop in enumerate(session_obj.crops):
                if crop.versions:
                    continue
                seed = (session_obj.seed or 1) + idx
                crop_img, crop_mask = _crop_with_mask(source, crop)
                styled = style_crop(
                    crop_img,
                    crop_mask,
                    seed=seed,
                    controlnet_weight=settings.controlnet_weight,
                )

                version_no = 1
                relative_path = f"crops/{crop.id}/v{version_no}.png"
                image_url = storage.save_image(session_obj.id, relative_path, styled)
                params = {
                    "style_id": session_obj.style_id,
                    "seed": seed,
                    "steps": settings.sdxl_steps,
                    "cfg": settings.sdxl_cfg,
                    "size": settings.sdxl_size,
                    "controlnet_weight": settings.controlnet_weight,
                }
                db.add(
                    CropVersion(
                        id=str(uuid.uuid4()),
                        crop_id=crop.id,
                        version_no=version_no,
                        image_url=image_url,
                        seed=seed,
                        params_hash=_hash_params(params),
                        approved=False,
                    )
                )
                crop.status = CropStatus.GENERATED.value

            session_obj.status = SessionStatus.REVIEWING.value
            _job_update(db, job, JobStatus.SUCCEEDED)
            db.commit()
        except Exception as exc:
            _job_update(db, job, JobStatus.FAILED, str(exc))
            session_obj.status = SessionStatus.FAILED.value
            db.commit()
            raise


@shared_task(name="services.worker.tasks.regenerate_crop", bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 2})
def regenerate_crop(self, job_id: str, crop_id: str, seed: int):
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        crop = db.execute(select(Crop).where(Crop.id == crop_id).options(selectinload(Crop.versions), selectinload(Crop.session))).scalar_one_or_none()
        if not job or not crop:
            return

        try:
            _job_update(db, job, JobStatus.RUNNING)
            db.commit()

            session_obj = db.get(Session, crop.session_id)
            if not session_obj or not session_obj.style_id:
                raise RuntimeError("Session style is not locked")

            source = _open_image(session_obj.source_image_url)
            crop_img, crop_mask = _crop_with_mask(source, crop)
            styled = style_crop(crop_img, crop_mask, seed=seed, controlnet_weight=settings.controlnet_weight)

            version_no = (max([v.version_no for v in crop.versions]) + 1) if crop.versions else 1
            relative_path = f"crops/{crop.id}/v{version_no}.png"
            image_url = storage.save_image(session_obj.id, relative_path, styled)

            for version in crop.versions:
                version.approved = False

            params = {
                "style_id": session_obj.style_id,
                "seed": seed,
                "steps": settings.sdxl_steps,
                "cfg": settings.sdxl_cfg,
                "size": settings.sdxl_size,
                "controlnet_weight": settings.controlnet_weight,
            }
            db.add(
                CropVersion(
                    id=str(uuid.uuid4()),
                    crop_id=crop.id,
                    version_no=version_no,
                    image_url=image_url,
                    seed=seed,
                    params_hash=_hash_params(params),
                    approved=False,
                )
            )

            crop.status = CropStatus.GENERATED.value
            session_obj.status = SessionStatus.REVIEWING.value

            _job_update(db, job, JobStatus.SUCCEEDED)
            db.commit()
        except Exception as exc:
            _job_update(db, job, JobStatus.FAILED, str(exc))
            db.commit()
            raise


@shared_task(name="services.worker.tasks.compose_session", bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 2})
def compose_session(self, job_id: str, session_id: str, seam_pass_count: int):
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        session_obj = db.execute(
            select(Session)
            .where(Session.id == session_id)
            .options(selectinload(Session.crops).selectinload(Crop.versions), selectinload(Session.compose_results))
        ).scalar_one_or_none()

        if not job or not session_obj:
            return

        try:
            _job_update(db, job, JobStatus.RUNNING)
            db.commit()

            source = _open_image(session_obj.source_image_url)
            layers: list[Layer] = []
            for crop in session_obj.crops:
                approved_versions = [v for v in crop.versions if v.approved]
                if not approved_versions:
                    raise RuntimeError(f"Crop {crop.id} is not approved")
                version = max(approved_versions, key=lambda x: x.version_no)
                layer_img = _open_image(version.image_url).convert("RGBA")
                layers.append(
                    Layer(
                        image=layer_img,
                        bbox_x=crop.bbox_x,
                        bbox_y=crop.bbox_y,
                        bbox_w=crop.bbox_w,
                        bbox_h=crop.bbox_h,
                        mask_rle=crop.mask_rle,
                    )
                )

            composed = compose_with_seam_refine(source.convert("RGB"), layers, seam_pass_count=seam_pass_count)
            image_url = storage.save_image(session_obj.id, "compose/final.png", composed)
            db.add(
                ComposeResult(
                    id=str(uuid.uuid4()),
                    session_id=session_obj.id,
                    image_url=image_url,
                    seam_pass_count=seam_pass_count,
                    quality_score=None,
                )
            )
            session_obj.status = SessionStatus.DONE.value
            _job_update(db, job, JobStatus.SUCCEEDED)
            db.commit()
        except Exception as exc:
            _job_update(db, job, JobStatus.FAILED, str(exc))
            session_obj.status = SessionStatus.FAILED.value
            db.commit()
            raise
