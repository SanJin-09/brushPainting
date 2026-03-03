from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from services.api.app.models.enums import CropStatus, JobStatus, SessionStatus


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

    crops: Mapped[list["Crop"]] = relationship(back_populates="session", cascade="all, delete-orphan")
    compose_results: Mapped[list["ComposeResult"]] = relationship(back_populates="session", cascade="all, delete-orphan")
    jobs: Mapped[list["Job"]] = relationship(back_populates="session")


class Crop(Base):
    __tablename__ = "crops"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    bbox_x: Mapped[int] = mapped_column(Integer, nullable=False)
    bbox_y: Mapped[int] = mapped_column(Integer, nullable=False)
    bbox_w: Mapped[int] = mapped_column(Integer, nullable=False)
    bbox_h: Mapped[int] = mapped_column(Integer, nullable=False)
    mask_rle: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default=CropStatus.PENDING.value, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    session: Mapped[Session] = relationship(back_populates="crops")
    versions: Mapped[list["CropVersion"]] = relationship(back_populates="crop", cascade="all, delete-orphan", order_by="CropVersion.version_no")


class CropVersion(Base):
    __tablename__ = "crop_versions"
    __table_args__ = (UniqueConstraint("crop_id", "version_no", name="uq_crop_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    crop_id: Mapped[str] = mapped_column(ForeignKey("crops.id", ondelete="CASCADE"), index=True)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    image_url: Mapped[str] = mapped_column(Text, nullable=False)
    seed: Mapped[int] = mapped_column(nullable=False)
    params_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    crop: Mapped[Crop] = relationship(back_populates="versions")


class ComposeResult(Base):
    __tablename__ = "compose_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    image_url: Mapped[str] = mapped_column(Text, nullable=False)
    seam_pass_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    quality_score: Mapped[float | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    session: Mapped[Session] = relationship(back_populates="compose_results")


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
