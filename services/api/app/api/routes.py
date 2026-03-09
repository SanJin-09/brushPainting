from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from PIL import Image
from sqlalchemy.orm import Session

from model_runtime.mask_assist import refine_mask
from services.api.app.db.database import get_db
from services.api.app.models.entities import Job
from services.api.app.models.enums import SessionStatus
from services.api.app.schemas.job import JobRead
from services.api.app.schemas.session import (
    EditRequest,
    ExportResponse,
    MaskAssistRequest,
    MaskAssistResponse,
    RenderRequest,
    SessionCreateResponse,
    SessionRead,
    StyleLockRequest,
)
from services.api.app.services.errors import ServiceError
from services.api.app.services.job_service import create_job, dispatch_job
from services.api.app.services.session_service import (
    adopt_version,
    create_session,
    current_export_version,
    decode_and_validate_mask,
    ensure_can_edit,
    ensure_can_mask_assist,
    ensure_can_render,
    ensure_mask_inside_bbox,
    get_session,
    lock_style,
    mark_done,
    next_seed,
    validate_bbox,
)
from services.api.app.services.storage import LocalMediaStorage

router = APIRouter(prefix="/api/v1", tags=["v1"])
storage = LocalMediaStorage()


def _raise_service_error(exc: ServiceError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=str(exc))


def _open_media_image(url: str) -> Image.Image:
    path = storage.url_to_path(url)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Media image not found")
    return Image.open(path)


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


@router.post("/sessions/{session_id}/style/lock", response_model=SessionRead)
def lock_style_endpoint(session_id: str, body: StyleLockRequest, db: Session = Depends(get_db)):
    try:
        return lock_style(db, session_id, body.style_id)
    except ServiceError as exc:
        _raise_service_error(exc)


@router.post("/sessions/{session_id}/render", response_model=JobRead)
def render_session_endpoint(session_id: str, body: RenderRequest, db: Session = Depends(get_db)):
    try:
        session_obj = get_session(db, session_id)
        ensure_can_render(session_obj)
    except ServiceError as exc:
        _raise_service_error(exc)

    seed = next_seed(body.seed)
    session_obj.seed = seed
    session_obj.status = SessionStatus.RENDERING.value
    job = create_job(
        db,
        job_type="render_full",
        session_id=session_id,
        payload={"seed": seed},
    )
    dispatch_job("services.worker.tasks.render_full", job.id, session_id, seed)
    return job


@router.post("/sessions/{session_id}/mask-assist", response_model=MaskAssistResponse)
def mask_assist_endpoint(session_id: str, body: MaskAssistRequest, db: Session = Depends(get_db)):
    try:
        session_obj = get_session(db, session_id)
        current_version = ensure_can_mask_assist(session_obj)
        with _open_media_image(current_version.image_url) as current_image:
            mask = decode_and_validate_mask(body.mask_rle, image_size=current_image.size)
            refined = refine_mask(current_image.convert("RGB"), mask)
        return MaskAssistResponse(
            mask_rle=refined.mask_rle,
            bbox_x=refined.bbox_x,
            bbox_y=refined.bbox_y,
            bbox_w=refined.bbox_w,
            bbox_h=refined.bbox_h,
        )
    except ServiceError as exc:
        _raise_service_error(exc)


@router.post("/sessions/{session_id}/edits", response_model=JobRead)
def create_edit_endpoint(session_id: str, body: EditRequest, db: Session = Depends(get_db)):
    try:
        session_obj = get_session(db, session_id)
        current_version = ensure_can_edit(session_obj)
        with _open_media_image(current_version.image_url) as current_image:
            mask = decode_and_validate_mask(body.mask_rle, image_size=current_image.size)
            validate_bbox(body.bbox_x, body.bbox_y, body.bbox_w, body.bbox_h, image_size=current_image.size)
            ensure_mask_inside_bbox(mask, body.bbox_x, body.bbox_y, body.bbox_w, body.bbox_h)
    except ServiceError as exc:
        _raise_service_error(exc)

    seed = next_seed(body.seed)
    session_obj.seed = seed
    session_obj.status = SessionStatus.EDITING.value
    job = create_job(
        db,
        job_type="edit_mask",
        session_id=session_id,
        payload={
            "seed": seed,
            "mask_rle": body.mask_rle,
            "bbox": [body.bbox_x, body.bbox_y, body.bbox_w, body.bbox_h],
            "prompt_override": body.prompt_override,
        },
    )
    dispatch_job(
        "services.worker.tasks.edit_mask",
        job.id,
        session_id,
        seed,
        body.mask_rle,
        body.bbox_x,
        body.bbox_y,
        body.bbox_w,
        body.bbox_h,
        body.prompt_override,
    )
    return job


@router.post("/sessions/{session_id}/versions/{version_id}/adopt", response_model=SessionRead)
def adopt_version_endpoint(session_id: str, version_id: str, db: Session = Depends(get_db)):
    try:
        return adopt_version(db, session_id, version_id)
    except ServiceError as exc:
        _raise_service_error(exc)


@router.post("/sessions/{session_id}/export", response_model=ExportResponse)
def export_session_endpoint(session_id: str, db: Session = Depends(get_db)):
    try:
        session_obj = get_session(db, session_id)
        current = current_export_version(session_obj)
    except ServiceError as exc:
        _raise_service_error(exc)

    manifest = {
        "session_id": session_obj.id,
        "style_id": session_obj.style_id,
        "status": SessionStatus.DONE.value,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "seed": session_obj.seed,
        "source_image_url": session_obj.source_image_url,
        "current_version_id": current.id,
        "final_image_url": current.image_url,
        "versions": [
            {
                "id": version.id,
                "session_id": version.session_id,
                "parent_version_id": version.parent_version_id,
                "kind": version.kind,
                "image_url": version.image_url,
                "seed": version.seed,
                "params_hash": version.params_hash,
                "is_current": version.is_current,
                "prompt_override": version.prompt_override,
                "mask_rle": version.mask_rle,
                "bbox": [version.bbox_x, version.bbox_y, version.bbox_w, version.bbox_h]
                if version.bbox_x is not None
                else None,
                "created_at": version.created_at.isoformat(),
            }
            for version in session_obj.versions
        ],
    }
    manifest_url = storage.save_json(
        session_id,
        "export/manifest.json",
        json.dumps(manifest, ensure_ascii=False, indent=2),
    )
    mark_done(db, session_obj)
    return ExportResponse(session_id=session_id, final_image_url=current.image_url, manifest_url=manifest_url)


@router.get("/jobs/{job_id}", response_model=JobRead)
def get_job_endpoint(job_id: str, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return job
