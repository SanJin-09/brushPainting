from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ReferenceReviewImageRead(BaseModel):
    file_name: str
    relative_path: str


class ReferenceReviewRead(BaseModel):
    directory: str
    current: ReferenceReviewImageRead | None
    pending_count: int
    keep_count: int
    discard_count: int
    reviewed_count: int
    total_count: int
    history_count: int
    keep_hotkey: str
    discard_hotkey: str
    undo_hotkey: str


class ReferenceReviewActionRequest(BaseModel):
    directory: str = Field(min_length=1)
    relative_path: str = Field(min_length=1)
    action: Literal["keep", "discard"]


class ReferenceReviewUndoRequest(BaseModel):
    directory: str = Field(min_length=1)
