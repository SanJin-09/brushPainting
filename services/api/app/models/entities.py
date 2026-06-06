from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from services.api.app.models.enums import ImageStatus, JobStatus


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Batch(Base):
    __tablename__ = "batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    images: Mapped[list["ImageAsset"]] = relationship(
        back_populates="batch",
        cascade="all, delete-orphan",
        order_by="ImageAsset.created_at",
    )
    jobs: Mapped[list["Job"]] = relationship(back_populates="batch")


class ImageAsset(Base):
    __tablename__ = "images"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("batches.id", ondelete="CASCADE"), index=True)
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    original_url: Mapped[str] = mapped_column(Text, nullable=False)
    thumbnail_url: Mapped[str] = mapped_column(Text, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default=ImageStatus.UPLOADED.value, nullable=False)
    active_version_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("versions.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    batch: Mapped[Batch] = relationship(back_populates="images")
    versions: Mapped[list["Version"]] = relationship(
        back_populates="image",
        cascade="all, delete-orphan",
        foreign_keys="Version.image_id",
        order_by="Version.created_at",
    )
    active_version: Mapped[Optional["Version"]] = relationship(foreign_keys=[active_version_id], post_update=True)
    jobs: Mapped[list["Job"]] = relationship(back_populates="image")


class Version(Base):
    __tablename__ = "versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    image_id: Mapped[str] = mapped_column(ForeignKey("images.id", ondelete="CASCADE"), index=True)
    parent_version_id: Mapped[Optional[str]] = mapped_column(ForeignKey("versions.id", ondelete="SET NULL"), nullable=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    output_url: Mapped[str] = mapped_column(Text, nullable=False)
    user_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    params_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    image: Mapped[ImageAsset] = relationship(back_populates="versions", foreign_keys=[image_id])
    parent_version: Mapped[Optional["Version"]] = relationship(remote_side="Version.id")


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        Index(
            "uq_jobs_active_image",
            "image_id",
            unique=True,
            sqlite_where=text("status IN ('queued', 'running')"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    batch_id: Mapped[Optional[str]] = mapped_column(ForeignKey("batches.id", ondelete="SET NULL"), index=True)
    image_id: Mapped[Optional[str]] = mapped_column(ForeignKey("images.id", ondelete="SET NULL"), index=True)
    status: Mapped[str] = mapped_column(String(32), default=JobStatus.QUEUED.value, nullable=False)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    progress_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    input_payload: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    result_version_id: Mapped[Optional[str]] = mapped_column(ForeignKey("versions.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    batch: Mapped[Optional[Batch]] = relationship(back_populates="jobs")
    image: Mapped[Optional[ImageAsset]] = relationship(back_populates="jobs")
    result_version: Mapped[Optional[Version]] = relationship(foreign_keys=[result_version_id])
