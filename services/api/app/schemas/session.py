from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SessionCreateResponse(BaseModel):
    session_id: str
    source_image_url: str
    status: str


class SegmentRequest(BaseModel):
    seed: int | None = None
    crop_count: int = Field(default=6, ge=1, le=24)


class StyleLockRequest(BaseModel):
    style_id: str = Field(min_length=1, max_length=128)


class GenerateRequest(BaseModel):
    force_regenerate_missing: bool = True


class RegenerateRequest(BaseModel):
    seed: int | None = None


class ComposeRequest(BaseModel):
    seam_pass_count: int = Field(default=1, ge=1, le=3)


class CropVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    version_no: int
    image_url: str
    seed: int
    params_hash: str
    approved: bool
    created_at: datetime


class CropRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    bbox_x: int
    bbox_y: int
    bbox_w: int
    bbox_h: int
    status: str
    created_at: datetime
    versions: list[CropVersionRead]


class ComposeResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    image_url: str
    seam_pass_count: int
    quality_score: float | None
    created_at: datetime


class SessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_image_url: str
    style_id: str | None
    status: str
    seed: int | None
    created_at: datetime
    updated_at: datetime
    crops: list[CropRead]
    compose_results: list[ComposeResultRead]


class ExportResponse(BaseModel):
    session_id: str
    final_image_url: str
    manifest_url: str
