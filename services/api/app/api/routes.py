from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from services.api.app.db.database import get_db
from services.api.app.models.entities import Crop, Job
from services.api.app.models.enums import SessionStatus
from services.api.app.schemas.job import JobRead
from services.api.app.schemas.session import (
    ComposeRequest,
    ExportResponse,
    GenerateRequest,
    RegenerateRequest,
    SegmentRequest,
    SessionCreateResponse,
    SessionRead,
    StyleLockRequest,
)
from services.api.app.services.errors import ServiceError
from services.api.app.services.job_service import create_job, dispatch_job
from services.api.app.services.session_service import (
    approve_crop,
    create_session,
    ensure_can_compose,
    ensure_can_generate,
    get_session,
    latest_compose_result,
    lock_style,
    next_seed,
    reset_generation,
    validate_crop_count,
)
from services.api.app.services.storage import LocalMediaStorage

router = APIRouter(prefix="/api/v1", tags=["v1"])
storage = LocalMediaStorage()


def _raise_service_error(exc: ServiceError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=str(exc))


@router.post("/sessions", response_model=SessionCreateResponse)
def create_session_endpoint(file: UploadFile = File(...), db: Session = Depends(get_db)):
    try:
        session_obj = create_session(db, file)
    except ServiceError as exc:
        _raise_service_error(exc)

    return SessionCreateResponse(
        session_id=session_obj.id,
        source_image_url=session_obj.source_image_url,
        status=session_obj.status,
    )


@router.get("/sessions/{session_id}", response_model=SessionRead)
def get_session_endpoint(session_id: str, db: Session = Depends(get_db)):
    try:
        return get_session(db, session_id)
    except ServiceError as exc:
        _raise_service_error(exc)


@router.post("/sessions/{session_id}/segment", response_model=JobRead)
def segment_session_endpoint(session_id: str, body: SegmentRequest, db: Session = Depends(get_db)):
    try:
        validate_crop_count(body.crop_count)
        session_obj = get_session(db, session_id)
    except ServiceError as exc:
        _raise_service_error(exc)

    seed = next_seed(body.seed)
    session_obj.seed = seed
    job = create_job(
        db,
        job_type="segment",
        session_id=session_id,
        payload={"seed": seed, "crop_count": body.crop_count},
    )
    dispatch_job("services.worker.tasks.segment_session", job.id, session_id, seed, body.crop_count)
    db.commit()
    db.refresh(job)
    return job


@router.post("/sessions/{session_id}/style/lock", response_model=SessionRead)
def lock_style_endpoint(session_id: str, body: StyleLockRequest, db: Session = Depends(get_db)):
    try:
        return lock_style(db, session_id, body.style_id)
    except ServiceError as exc:
        _raise_service_error(exc)


@router.post("/sessions/{session_id}/reset-generation", response_model=SessionRead)
def reset_generation_endpoint(session_id: str, db: Session = Depends(get_db)):
    try:
        return reset_generation(db, session_id)
    except ServiceError as exc:
        _raise_service_error(exc)


@router.post("/sessions/{session_id}/crops/generate", response_model=JobRead)
def generate_crops_endpoint(session_id: str, _: GenerateRequest, db: Session = Depends(get_db)):
    try:
        session_obj = get_session(db, session_id)
        ensure_can_generate(session_obj)
    except ServiceError as exc:
        _raise_service_error(exc)

    session_obj.status = SessionStatus.GENERATING.value
    job = create_job(db, job_type="generate_all", session_id=session_id, payload={})
    dispatch_job("services.worker.tasks.generate_all_crops", job.id, session_id)
    db.commit()
    db.refresh(job)
    return job


@router.post("/crops/{crop_id}/regenerate", response_model=JobRead)
def regenerate_crop_endpoint(crop_id: str, body: RegenerateRequest, db: Session = Depends(get_db)):
    crop = db.get(Crop, crop_id)
    if not crop:
        raise HTTPException(status_code=404, detail=f"Crop {crop_id} not found")
    seed = next_seed(body.seed)
    job = create_job(
        db,
        job_type="regenerate",
        session_id=crop.session_id,
        payload={"crop_id": crop_id, "seed": seed},
    )
    dispatch_job("services.worker.tasks.regenerate_crop", job.id, crop_id, seed)
    return job


@router.post("/crops/{crop_id}/approve", response_model=SessionRead)
def approve_crop_endpoint(crop_id: str, db: Session = Depends(get_db)):
    try:
        crop = approve_crop(db, crop_id)
        session_obj = get_session(db, crop.session_id)
        return session_obj
    except ServiceError as exc:
        _raise_service_error(exc)


@router.post("/sessions/{session_id}/compose", response_model=JobRead)
def compose_session_endpoint(session_id: str, body: ComposeRequest, db: Session = Depends(get_db)):
    try:
        session_obj = get_session(db, session_id)
        ensure_can_compose(session_obj)
    except ServiceError as exc:
        _raise_service_error(exc)

    session_obj.status = SessionStatus.COMPOSING.value
    job = create_job(
        db,
        job_type="compose",
        session_id=session_id,
        payload={"seam_pass_count": body.seam_pass_count},
    )
    dispatch_job("services.worker.tasks.compose_session", job.id, session_id, body.seam_pass_count)
    db.commit()
    db.refresh(job)
    return job


@router.post("/sessions/{session_id}/export", response_model=ExportResponse)
def export_session_endpoint(session_id: str, db: Session = Depends(get_db)):
    try:
        session_obj = get_session(db, session_id)
    except ServiceError as exc:
        _raise_service_error(exc)

    result = latest_compose_result(session_obj)
    if not result:
        raise HTTPException(status_code=409, detail="No compose result available")

    manifest = {
        "session_id": session_obj.id,
        "style_id": session_obj.style_id,
        "status": session_obj.status,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "seed": session_obj.seed,
        "source_image_url": session_obj.source_image_url,
        "final_image_url": result.image_url,
        "crop_count": len(session_obj.crops),
        "crops": [
            {
                "crop_id": crop.id,
                "bbox": [crop.bbox_x, crop.bbox_y, crop.bbox_w, crop.bbox_h],
                "status": crop.status,
                "versions": [
                    {
                        "id": version.id,
                        "version_no": version.version_no,
                        "image_url": version.image_url,
                        "seed": version.seed,
                        "approved": version.approved,
                    }
                    for version in crop.versions
                ],
            }
            for crop in session_obj.crops
        ],
    }
    manifest_url = storage.save_json(session_id, "export/manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    return ExportResponse(session_id=session_id, final_image_url=result.image_url, manifest_url=manifest_url)


@router.get("/jobs/{job_id}", response_model=JobRead)
def get_job_endpoint(job_id: str, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return job
