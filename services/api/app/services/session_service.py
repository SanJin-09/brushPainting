from __future__ import annotations

import hashlib
import json
import random
import uuid
from typing import Any

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from services.api.app.core.config import get_settings
from services.api.app.models.entities import ComposeResult, Crop, CropVersion, Session as SessionModel
from services.api.app.models.enums import CropStatus, SessionStatus
from services.api.app.services.errors import ConflictError, NotFoundError, ValidationError
from services.api.app.services.storage import LocalMediaStorage

settings = get_settings()
storage = LocalMediaStorage()


def _session_with_relations_query(session_id: str):
    return (
        select(SessionModel)
        .where(SessionModel.id == session_id)
        .options(
            selectinload(SessionModel.crops).selectinload(Crop.versions),
            selectinload(SessionModel.compose_results),
        )
    )


def create_session(db: Session, file: UploadFile) -> SessionModel:
    raw = file.file.read()
    if not raw:
        raise ValidationError("Uploaded file is empty")

    session_id = str(uuid.uuid4())
    source_url = storage.save_source(session_id, file.filename or "source.png", raw)
    obj = SessionModel(
        id=session_id,
        source_image_url=source_url,
        status=SessionStatus.UPLOADED.value,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def get_session(db: Session, session_id: str) -> SessionModel:
    obj = db.execute(_session_with_relations_query(session_id)).scalar_one_or_none()
    if not obj:
        raise NotFoundError(f"Session {session_id} not found")
    return obj


def lock_style(db: Session, session_id: str, style_id: str) -> SessionModel:
    session_obj = get_session(db, session_id)
    if style_id != settings.default_style_id:
        raise ValidationError(f"Unsupported style_id: {style_id}, expected {settings.default_style_id}")

    has_versions = any(crop.versions for crop in session_obj.crops)
    if has_versions and session_obj.style_id and session_obj.style_id != style_id:
        raise ConflictError("Style cannot be changed after crop generation; reset generation first")

    session_obj.style_id = style_id
    if session_obj.status in {SessionStatus.SEGMENTED.value, SessionStatus.UPLOADED.value}:
        session_obj.status = SessionStatus.STYLE_LOCKED.value
    db.commit()
    return get_session(db, session_id)


def validate_crop_count(crop_count: int) -> None:
    if crop_count < settings.min_crop_count or crop_count > settings.max_crop_count:
        raise ValidationError(f"crop_count must be between {settings.min_crop_count} and {settings.max_crop_count}")


def next_seed(seed: int | None) -> int:
    if seed is not None:
        return seed
    return random.randint(1, 2**31 - 1)


def mark_ready_if_all_approved(db: Session, session_obj: SessionModel) -> None:
    if not session_obj.crops:
        return
    if all(crop.status == CropStatus.APPROVED.value for crop in session_obj.crops):
        session_obj.status = SessionStatus.READY_TO_COMPOSE.value
        db.commit()


def approve_crop(db: Session, crop_id: str) -> Crop:
    crop = db.get(Crop, crop_id)
    if not crop:
        raise NotFoundError(f"Crop {crop_id} not found")

    if not crop.versions:
        raise ValidationError("Crop has no generated version")

    latest = max(crop.versions, key=lambda x: x.version_no)
    for version in crop.versions:
        version.approved = version.id == latest.id

    crop.status = CropStatus.APPROVED.value
    session_obj = db.get(SessionModel, crop.session_id)
    if session_obj:
        mark_ready_if_all_approved(db, session_obj)
    db.commit()
    db.refresh(crop)
    return crop


def ensure_can_generate(session_obj: SessionModel) -> None:
    if not session_obj.style_id:
        raise ValidationError("Style must be locked before generation")
    if not session_obj.crops:
        raise ValidationError("Session must be segmented before generation")


def ensure_can_compose(session_obj: SessionModel) -> None:
    if not session_obj.crops:
        raise ValidationError("No crops to compose")
    if any(crop.status != CropStatus.APPROVED.value for crop in session_obj.crops):
        raise ValidationError("All crops must be approved before compose")


def params_hash(payload: dict[str, Any]) -> str:
    normalized = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]


def latest_compose_result(session_obj: SessionModel) -> ComposeResult | None:
    if not session_obj.compose_results:
        return None
    return max(session_obj.compose_results, key=lambda x: x.created_at)


def reset_generation(db: Session, session_id: str) -> SessionModel:
    session_obj = get_session(db, session_id)
    for crop in session_obj.crops:
        for version in crop.versions:
            db.delete(version)
        crop.status = CropStatus.PENDING.value

    session_obj.status = SessionStatus.STYLE_LOCKED.value if session_obj.style_id else SessionStatus.SEGMENTED.value
    db.commit()
    return get_session(db, session_id)
