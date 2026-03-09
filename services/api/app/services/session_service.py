from __future__ import annotations

import hashlib
import json
import random
import uuid

import numpy as np
from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from model_runtime.rle import decode_mask_rle
from services.api.app.core.config import get_settings
from services.api.app.models.entities import ImageVersion, Session as SessionModel
from services.api.app.models.enums import SessionStatus
from services.api.app.services.errors import ConflictError, NotFoundError, ValidationError
from services.api.app.services.storage import LocalMediaStorage

settings = get_settings()
storage = LocalMediaStorage()


def _session_with_relations_query(session_id: str):
    return (
        select(SessionModel)
        .where(SessionModel.id == session_id)
        .options(selectinload(SessionModel.versions))
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

    if session_obj.versions and session_obj.style_id and session_obj.style_id != style_id:
        raise ConflictError("Style cannot be changed after image generation")

    session_obj.style_id = style_id
    if session_obj.status in {SessionStatus.UPLOADED.value, SessionStatus.FAILED.value}:
        session_obj.status = SessionStatus.STYLE_LOCKED.value
    db.commit()
    return get_session(db, session_id)


def next_seed(seed: int | None) -> int:
    if seed is not None:
        return seed
    return random.randint(1, 2**31 - 1)


def ensure_can_render(session_obj: SessionModel) -> None:
    if not session_obj.style_id:
        raise ValidationError("Style must be locked before rendering")


def current_version_or_raise(session_obj: SessionModel) -> ImageVersion:
    current = session_obj.current_version
    if not current:
        raise ValidationError("Session has no current version")
    return current


def ensure_can_mask_assist(session_obj: SessionModel) -> ImageVersion:
    return current_version_or_raise(session_obj)


def ensure_can_edit(session_obj: SessionModel) -> ImageVersion:
    return current_version_or_raise(session_obj)


def get_version_or_raise(session_obj: SessionModel, version_id: str) -> ImageVersion:
    for version in session_obj.versions:
        if version.id == version_id:
            return version
    raise NotFoundError(f"Version {version_id} not found in session {session_obj.id}")


def adopt_version(db: Session, session_id: str, version_id: str) -> SessionModel:
    session_obj = get_session(db, session_id)
    target = get_version_or_raise(session_obj, version_id)

    for version in session_obj.versions:
        version.is_current = version.id == target.id

    session_obj.status = SessionStatus.REVIEWING.value
    db.commit()
    return get_session(db, session_id)


def params_hash(payload: dict[str, object]) -> str:
    normalized = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]


def current_export_version(session_obj: SessionModel) -> ImageVersion:
    return current_version_or_raise(session_obj)


def mark_done(db: Session, session_obj: SessionModel) -> None:
    session_obj.status = SessionStatus.DONE.value
    db.commit()


def decode_and_validate_mask(mask_rle: str, *, image_size: tuple[int, int]) -> np.ndarray:
    try:
        mask = decode_mask_rle(mask_rle)
    except Exception as exc:
        raise ValidationError("Invalid mask_rle") from exc

    width, height = image_size
    if mask.shape != (height, width):
        raise ValidationError(f"Mask shape must be {(height, width)}, got {mask.shape}")
    mask = (mask.astype(np.uint8) > 0).astype(np.uint8)
    if int(mask.sum()) == 0:
        raise ValidationError("Mask must contain at least one selected pixel")
    return mask


def bbox_from_mask(mask: np.ndarray) -> tuple[int, int, int, int]:
    ys, xs = np.where(mask > 0)
    if xs.size == 0 or ys.size == 0:
        raise ValidationError("Mask must contain at least one selected pixel")

    x0 = int(xs.min())
    y0 = int(ys.min())
    x1 = int(xs.max()) + 1
    y1 = int(ys.max()) + 1
    return x0, y0, x1 - x0, y1 - y0


def validate_bbox(
    bbox_x: int,
    bbox_y: int,
    bbox_w: int,
    bbox_h: int,
    *,
    image_size: tuple[int, int],
) -> None:
    width, height = image_size
    if bbox_x < 0 or bbox_y < 0 or bbox_w <= 0 or bbox_h <= 0:
        raise ValidationError("bbox must be positive and within image bounds")
    if bbox_x + bbox_w > width or bbox_y + bbox_h > height:
        raise ValidationError("bbox exceeds image bounds")


def ensure_mask_inside_bbox(mask: np.ndarray, bbox_x: int, bbox_y: int, bbox_w: int, bbox_h: int) -> None:
    ys, xs = np.where(mask > 0)
    if xs.size == 0 or ys.size == 0:
        raise ValidationError("Mask must contain at least one selected pixel")

    if int(xs.min()) < bbox_x or int(xs.max()) >= bbox_x + bbox_w:
        raise ValidationError("Mask must be fully contained inside bbox")
    if int(ys.min()) < bbox_y or int(ys.max()) >= bbox_y + bbox_h:
        raise ValidationError("Mask must be fully contained inside bbox")
