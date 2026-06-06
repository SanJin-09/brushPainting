from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class RegenerateRequest(BaseModel):
    seed: int | None = None


class SemanticEditRequest(BaseModel):
    version_id: str = Field(min_length=1)
    user_prompt: str = Field(min_length=1, max_length=500)
    seed: int | None = None

    @field_validator("user_prompt")
    @classmethod
    def validate_user_prompt(cls, value: str) -> str:
        prompt = value.strip()
        if not prompt:
            raise ValueError("user_prompt 不能为空")
        return prompt


class ExportRequest(BaseModel):
    image_ids: list[str] | None = None


class VersionRead(BaseModel):
    id: str
    image_id: str
    parent_version_id: str | None
    kind: str
    output_url: str
    user_prompt: str | None
    seed: int
    params: dict | None
    created_at: datetime


class JobRead(BaseModel):
    id: str
    type: str
    batch_id: str | None
    image_id: str | None
    status: str
    progress: int
    progress_message: str | None
    error: str | None
    result_version_id: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class ImageRead(BaseModel):
    id: str
    batch_id: str
    filename: str
    original_url: str
    thumbnail_url: str
    width: int
    height: int
    status: str
    active_version_id: str | None
    active_version: VersionRead | None
    latest_job: JobRead | None
    created_at: datetime
    updated_at: datetime


class UploadResponse(BaseModel):
    batch_id: str
    images: list[ImageRead]


class BatchRead(BaseModel):
    id: str
    status: str
    images: list[ImageRead]
    created_at: datetime
    updated_at: datetime


class JobsResponse(BaseModel):
    jobs: list[JobRead]


class VersionsResponse(BaseModel):
    image_id: str
    active_version_id: str | None
    versions: list[VersionRead]


class ExportResponse(BaseModel):
    batch_id: str
    zip_url: str
