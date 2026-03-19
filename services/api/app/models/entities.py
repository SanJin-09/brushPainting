from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from services.api.app.models.enums import ImageVersionKind, JobStatus, SessionStatus


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_image_url: Mapped[str] = mapped_column(Text, nullable=False)
    style_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default=SessionStatus.UPLOADED.value, nullable=False)
    seed: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    versions: Mapped[list["ImageVersion"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ImageVersion.created_at",
    )
    jobs: Mapped[list["Job"]] = relationship(back_populates="session")

    @property
    def current_version(self) -> ImageVersion | None:
        for version in reversed(self.versions):
            if version.is_current:
                return version
        return None

    @property
    def current_version_id(self) -> str | None:
        current = self.current_version
        return current.id if current else None


class ImageVersion(Base):
    __tablename__ = "image_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    parent_version_id: Mapped[str | None] = mapped_column(ForeignKey("image_versions.id", ondelete="SET NULL"), nullable=True)
    kind: Mapped[str] = mapped_column(String(32), default=ImageVersionKind.FULL_RENDER.value, nullable=False)
    image_url: Mapped[str] = mapped_column(Text, nullable=False)
    seed: Mapped[int] = mapped_column(nullable=False)
    params_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    prompt_override: Mapped[str | None] = mapped_column(Text, nullable=True)
    mask_rle: Mapped[str | None] = mapped_column(Text, nullable=True)
    bbox_x: Mapped[int | None] = mapped_column(nullable=True)
    bbox_y: Mapped[int | None] = mapped_column(nullable=True)
    bbox_w: Mapped[int | None] = mapped_column(nullable=True)
    bbox_h: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    session: Mapped[Session] = relationship(back_populates="versions")
    parent_version: Mapped["ImageVersion | None"] = relationship(remote_side="ImageVersion.id")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("sessions.id", ondelete="SET NULL"), index=True)
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=JobStatus.QUEUED.value)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    session: Mapped[Session | None] = relationship(back_populates="jobs")

    @property
    def progress_percent(self) -> int | None:
        payload = self.payload_json or {}
        value = payload.get("progress_percent")
        if not isinstance(value, (int, float)):
            return None
        return max(0, min(100, int(value)))

    @property
    def progress_message(self) -> str | None:
        payload = self.payload_json or {}
        value = payload.get("progress_message")
        if not isinstance(value, str):
            return None
        return value.strip() or None
