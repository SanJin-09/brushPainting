from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.api.app.db.database import get_db
from services.api.app.models.entities import Batch, ImageAsset, Job, SegmentationResult, Version
from services.api.app.models.enums import ImageStatus, JobStatus, JobType
from services.api.app.schemas.workflow import (
    BatchRead,
    ExportRequest,
    ExportResponse,
    ImageRead,
    JobRead,
    JobsResponse,
    RegenerateRequest,
    SegmentRead,
    SegmentRequest,
    SegmentsResponse,
    SemanticEditRequest,
    UploadResponse,
    VersionRead,
    VersionsResponse,
)
from services.api.app.services.errors import ServiceError
from services.api.app.services.image_service import (
    active_job,
    create_batch,
    ensure_no_active_job,
    get_batch,
    get_image,
    get_version,
    latest_job,
    next_seed,
    validate_export_images,
)
from services.api.app.services.job_service import create_job, dispatch_job
from services.api.app.services.storage import LocalStorage

router = APIRouter(prefix="/api", tags=["api"])
storage = LocalStorage()


def _raise_service_error(exc: ServiceError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=str(exc))


def _version_read(version: Version | None) -> VersionRead | None:
    if version is None:
        return None
    return VersionRead(
        id=version.id,
        image_id=version.image_id,
        parent_version_id=version.parent_version_id,
        kind=version.kind,
        output_url=version.output_url,
        user_prompt=version.user_prompt,
        seed=version.seed,
        params=version.params_json,
        created_at=version.created_at,
    )


def _job_read(job: Job | None) -> JobRead | None:
    if job is None:
        return None
    return JobRead(
        id=job.id,
        type=job.type,
        batch_id=job.batch_id,
        image_id=job.image_id,
        status=job.status,
        progress=job.progress,
        progress_message=job.progress_message,
        error=job.error,
        result_version_id=job.result_version_id,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


def _image_read(image: ImageAsset) -> ImageRead:
    return ImageRead(
        id=image.id,
        batch_id=image.batch_id,
        filename=image.original_filename,
        original_url=image.original_url,
        thumbnail_url=image.thumbnail_url,
        width=image.width,
        height=image.height,
        status=image.status,
        active_version_id=image.active_version_id,
        active_version=_version_read(image.active_version),
        latest_job=_job_read(latest_job(image)),
        created_at=image.created_at,
        updated_at=image.updated_at,
    )


def _batch_status(batch: Batch) -> str:
    statuses = {image.status for image in batch.images}
    if ImageStatus.RUNNING.value in statuses:
        return ImageStatus.RUNNING.value
    if ImageStatus.QUEUED.value in statuses:
        return ImageStatus.QUEUED.value
    if statuses == {ImageStatus.SUCCEEDED.value}:
        return ImageStatus.SUCCEEDED.value
    if ImageStatus.FAILED.value in statuses:
        return ImageStatus.FAILED.value
    return ImageStatus.UPLOADED.value


def _batch_read(batch: Batch) -> BatchRead:
    return BatchRead(
        id=batch.id,
        status=_batch_status(batch),
        images=[_image_read(image) for image in batch.images],
        created_at=batch.created_at,
        updated_at=batch.updated_at,
    )


def _dispatch_or_fail(db: Session, job: Job, image: ImageAsset) -> None:
    try:
        dispatch_job(job.id, job.type)
    except ServiceError:
        job.status = JobStatus.FAILED.value
        job.error = "任务提交失败"
        image.status = ImageStatus.FAILED.value
        db.commit()
        raise


@router.post("/images/upload", response_model=UploadResponse)
def upload_images(files: list[UploadFile] = File(...), db: Session = Depends(get_db)):
    try:
        batch = create_batch(db, files)
        return UploadResponse(batch_id=batch.id, images=[_image_read(image) for image in batch.images])
    except ServiceError as exc:
        _raise_service_error(exc)


@router.get("/batches/{batch_id}", response_model=BatchRead)
def read_batch(batch_id: str, db: Session = Depends(get_db)):
    try:
        return _batch_read(get_batch(db, batch_id))
    except ServiceError as exc:
        _raise_service_error(exc)


@router.post("/batches/{batch_id}/generate", response_model=JobsResponse)
def generate_batch(batch_id: str, db: Session = Depends(get_db)):
    try:
        batch = get_batch(db, batch_id)
        jobs: list[Job] = []
        for image in batch.images:
            existing = active_job(image)
            if existing:
                jobs.append(existing)
                continue
            if image.versions:
                prior = next((job for job in reversed(image.jobs) if job.type == JobType.INITIAL.value), None)
                if prior:
                    jobs.append(prior)
                continue
            seed = next_seed(None)
            job = create_job(db, job_type=JobType.INITIAL.value, image=image, payload={"seed": seed})
            _dispatch_or_fail(db, job, image)
            jobs.append(job)
        return JobsResponse(jobs=[_job_read(job) for job in jobs if job is not None])
    except ServiceError as exc:
        _raise_service_error(exc)


@router.post("/images/{image_id}/regenerate", response_model=JobRead)
def regenerate_image(image_id: str, body: RegenerateRequest = RegenerateRequest(), db: Session = Depends(get_db)):
    try:
        image = get_image(db, image_id)
        ensure_no_active_job(image)
        job = create_job(
            db,
            job_type=JobType.REGENERATE.value,
            image=image,
            payload={"seed": next_seed(body.seed)},
        )
        _dispatch_or_fail(db, job, image)
        return _job_read(job)
    except ServiceError as exc:
        _raise_service_error(exc)


@router.post("/images/{image_id}/edit", response_model=JobRead)
def semantic_edit(image_id: str, body: SemanticEditRequest, db: Session = Depends(get_db)):
    try:
        image = get_image(db, image_id)
        ensure_no_active_job(image)
        get_version(image, body.version_id)
        job = create_job(
            db,
            job_type=JobType.SEMANTIC_EDIT.value,
            image=image,
            payload={
                "seed": next_seed(body.seed),
                "version_id": body.version_id,
                "user_prompt": body.user_prompt.strip(),
            },
        )
        _dispatch_or_fail(db, job, image)
        return _job_read(job)
    except ServiceError as exc:
        _raise_service_error(exc)


@router.get("/jobs/{job_id}", response_model=JobRead)
def read_job(job_id: str, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"任务 {job_id} 不存在")
    return _job_read(job)


@router.get("/images/{image_id}/versions", response_model=VersionsResponse)
def read_versions(image_id: str, db: Session = Depends(get_db)):
    try:
        image = get_image(db, image_id)
        return VersionsResponse(
            image_id=image.id,
            active_version_id=image.active_version_id,
            versions=[_version_read(version) for version in reversed(image.versions)],
        )
    except ServiceError as exc:
        _raise_service_error(exc)


@router.post("/batches/{batch_id}/export", response_model=ExportResponse)
def export_batch(batch_id: str, body: ExportRequest = ExportRequest(), db: Session = Depends(get_db)):
    try:
        batch = get_batch(db, batch_id)
        images = validate_export_images(batch, body.image_ids)
        zip_url = storage.create_export(
            batch.id,
            [(image.id, image.original_filename, image.active_version.output_url) for image in images if image.active_version],
        )
        return ExportResponse(batch_id=batch.id, zip_url=zip_url)
    except ServiceError as exc:
        _raise_service_error(exc)


def _segment_read(seg: SegmentationResult) -> SegmentRead:
    return SegmentRead(
        id=seg.id,
        source_image_id=seg.source_image_id,
        user_prompt=seg.user_prompt,
        region_index=seg.region_index,
        confidence=seg.confidence,
        mask_url=seg.mask_url,
        crop_url=seg.crop_url,
        bbox_x=seg.bbox_x,
        bbox_y=seg.bbox_y,
        bbox_w=seg.bbox_w,
        bbox_h=seg.bbox_h,
        area_ratio=seg.area_ratio,
        created_at=seg.created_at,
    )


@router.post("/images/{image_id}/segment", response_model=JobRead)
def segment_image_endpoint(image_id: str, body: SegmentRequest, db: Session = Depends(get_db)):
    try:
        image = get_image(db, image_id)
        ensure_no_active_job(image)
        job = create_job(
            db,
            job_type=JobType.SAM_SEGMENT.value,
            image=image,
            payload={"user_prompt": body.user_prompt.strip()},
        )
        _dispatch_or_fail(db, job, image)
        return _job_read(job)
    except ServiceError as exc:
        _raise_service_error(exc)


@router.get("/images/{image_id}/segments", response_model=SegmentsResponse)
def read_segments(image_id: str, db: Session = Depends(get_db)):
    try:
        image = get_image(db, image_id)
        segments = db.execute(
            select(SegmentationResult)
            .where(SegmentationResult.source_image_id == image_id)
            .order_by(SegmentationResult.user_prompt, SegmentationResult.region_index)
        ).scalars().all()
        return SegmentsResponse(
            source_image_id=image_id,
            user_prompt=segments[0].user_prompt if segments else "",
            segments=[_segment_read(s) for s in segments],
        )
    except ServiceError as exc:
        _raise_service_error(exc)


@router.get("/segments/{segment_id}", response_model=SegmentRead)
def read_segment(segment_id: str, db: Session = Depends(get_db)):
    seg = db.get(SegmentationResult, segment_id)
    if not seg:
        raise HTTPException(status_code=404, detail=f"子图 {segment_id} 不存在")
    return _segment_read(seg)


@router.get("/segments/{segment_id}/image")
def read_segment_image(segment_id: str, db: Session = Depends(get_db)):
    seg = db.get(SegmentationResult, segment_id)
    if not seg:
        raise HTTPException(status_code=404, detail=f"子图 {segment_id} 不存在")
    try:
        return FileResponse(storage.url_to_path(seg.crop_url))
    except ValueError:
        raise HTTPException(status_code=404, detail="子图文件不存在")

