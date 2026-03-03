from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    type: str
    session_id: str | None
    status: str
    error_message: str | None
    created_at: datetime
    updated_at: datetime
