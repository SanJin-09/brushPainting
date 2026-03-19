from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SessionCreateResponse(BaseModel):
    session_id: str
    source_image_url: str
    status: str


class StyleLockRequest(BaseModel):
    style_id: str = Field(min_length=1, max_length=128)


class RenderRequest(BaseModel):
    seed: int | None = None


class MaskAssistRequest(BaseModel):
    mask_rle: str = Field(min_length=1)


class MaskAssistResponse(BaseModel):
    mask_rle: str
    bbox_x: int
    bbox_y: int
    bbox_w: int
    bbox_h: int


class EditRequest(BaseModel):
    mask_rle: str = Field(min_length=1)
    bbox_x: int = Field(ge=0)
    bbox_y: int = Field(ge=0)
    bbox_w: int = Field(gt=0)
    bbox_h: int = Field(gt=0)
    seed: int | None = None
    prompt_override: str | None = Field(default=None, max_length=500)


class ExportResponse(BaseModel):
    session_id: str
    final_image_url: str
    manifest_url: str


class ImageVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    parent_version_id: str | None
    kind: str
    image_url: str
    seed: int
    params_hash: str
    is_current: bool
    prompt_override: str | None
    mask_rle: str | None
    bbox_x: int | None
    bbox_y: int | None
    bbox_w: int | None
    bbox_h: int | None
    created_at: datetime


class SessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_image_url: str
    style_id: str | None
    status: str
    seed: int | None
    current_version_id: str | None
    created_at: datetime
    updated_at: datetime
    supports_local_edit: bool
    local_edit_disabled_reason: str | None
    versions: list[ImageVersionRead]
