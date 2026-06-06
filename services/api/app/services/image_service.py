from __future__ import annotations

import random
import uuid
from collections.abc import Sequence

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from services.api.app.core.config import get_settings
from services.api.app.models.entities import Batch, ImageAsset, Job, Version
from services.api.app.models.enums import ImageStatus, JobStatus
from services.api.app.services.errors import ConflictError, NotFoundError, ValidationError
from services.api.app.services.storage import LocalStorage

settings = get_settings()
storage = LocalStorage()
ACTIVE_JOB_STATUSES = {JobStatus.QUEUED.value, JobStatus.RUNNING.value}


def next_seed(seed: int | None) -> int:
    return seed if seed is not None else random.randint(1, 2**31 - 1)


def create_batch(db: Session, files: Sequence[UploadFile]) -> Batch:
    if not files:
        raise ValidationError("请至少上传一张图片")
    if len(files) > settings.max_upload_files:
        raise ValidationError(f"每批最多上传 {settings.max_upload_files} 张图片")

    prepared = []
    for file in files:
        raw = file.file.read(settings.max_upload_bytes + 1)
        image = storage.prepare_upload(raw)
        prepared.append((file.filename or "image.png", image))

    batch = Batch(id=str(uuid.uuid4()))
    db.add(batch)
    db.flush()
    for filename, image in prepared:
        image_id = str(uuid.uuid4())
        original_url, thumbnail_url = storage.save_upload(batch.id, image_id, image)
        db.add(
            ImageAsset(
                id=image_id,
                batch_id=batch.id,
                original_filename=filename,
                original_url=original_url,
                thumbnail_url=thumbnail_url,
                width=image.width,
                height=image.height,
                status=ImageStatus.UPLOADED.value,
            )
        )
    db.commit()
    return get_batch(db, batch.id)


def get_batch(db: Session, batch_id: str) -> Batch:
    batch = db.execute(
        select(Batch)
        .where(Batch.id == batch_id)
        .options(selectinload(Batch.images).selectinload(ImageAsset.versions), selectinload(Batch.images).selectinload(ImageAsset.jobs))
    ).scalar_one_or_none()
    if not batch:
        raise NotFoundError(f"批次 {batch_id} 不存在")
    return batch


def get_image(db: Session, image_id: str) -> ImageAsset:
    image = db.execute(
        select(ImageAsset)
        .where(ImageAsset.id == image_id)
        .options(selectinload(ImageAsset.versions), selectinload(ImageAsset.jobs))
    ).scalar_one_or_none()
    if not image:
        raise NotFoundError(f"图片 {image_id} 不存在")
    return image


def get_version(image: ImageAsset, version_id: str) -> Version:
    for version in image.versions:
        if version.id == version_id:
            return version
    raise NotFoundError(f"版本 {version_id} 不属于图片 {image.id}")


def latest_job(image: ImageAsset) -> Job | None:
    return max(image.jobs, key=lambda job: job.created_at, default=None)


def active_job(image: ImageAsset) -> Job | None:
    return next((job for job in image.jobs if job.status in ACTIVE_JOB_STATUSES), None)


def ensure_no_active_job(image: ImageAsset) -> None:
    if active_job(image):
        raise ConflictError("该图片已有排队中或运行中的任务")


def validate_export_images(batch: Batch, image_ids: list[str] | None) -> list[ImageAsset]:
    selected = batch.images
    if image_ids is not None:
        if not image_ids:
            raise ValidationError("image_ids 不能为空数组")
        requested = set(image_ids)
        selected = [image for image in batch.images if image.id in requested]
        if len(selected) != len(requested):
            raise ValidationError("部分 image_ids 不属于该批次")
    if any(not image.active_version for image in selected):
        raise ConflictError("存在尚无可导出版本的图片")
    return selected
