from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(32), default="draft")
    current_stage: Mapped[str] = mapped_column(String(32), default="material")
    archived: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc
    )
    assets: Mapped[list["Asset"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="Asset.sequence_no"
    )


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    sequence_no: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(32), default="original")
    parent_asset_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    storage_key: Mapped[str] = mapped_column(String(1024), unique=True)
    original_name: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(64))
    file_size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    project: Mapped[Project] = relationship(back_populates="assets")


class Pattern(Base):
    __tablename__ = "patterns"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    source_asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"), index=True)
    board_layout: Mapped[str] = mapped_column(String(32))
    color_mode: Mapped[str] = mapped_column(String(16))
    palette_version: Mapped[str] = mapped_column(String(32), default="official-v1")
    pattern_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    versions: Mapped[list["PatternVersion"]] = relationship(
        back_populates="pattern", cascade="all, delete-orphan", order_by="PatternVersion.version_no"
    )


class PatternVersion(Base):
    __tablename__ = "pattern_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    pattern_id: Mapped[str] = mapped_column(ForeignKey("patterns.id"), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(120))
    note: Mapped[str] = mapped_column(String(500), default="")
    source_revision: Mapped[int] = mapped_column(Integer)
    pattern_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    pattern: Mapped[Pattern] = relationship(back_populates="versions")


class StageVersion(Base):
    """An immutable UI-stage snapshot.  It is deliberately separate from a
    PatternVersion: board planning, candidate selection and editing are not
    interchangeable states and must never be mixed in one history list.
    """
    __tablename__ = "stage_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    stage: Mapped[str] = mapped_column(String(24), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(120))
    snapshot_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class BatchJob(Base):
    __tablename__ = "batch_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    board_layout: Mapped[str] = mapped_column(String(32))
    color_mode: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc
    )
    items: Mapped[list["BatchItem"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="BatchItem.sequence_no"
    )


class BatchItem(Base):
    __tablename__ = "batch_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    batch_id: Mapped[str] = mapped_column(ForeignKey("batch_jobs.id"), index=True)
    sequence_no: Mapped[int] = mapped_column(Integer)
    source_asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    pattern_id: Mapped[str | None] = mapped_column(ForeignKey("patterns.id"), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    input_snapshot_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc
    )
    job: Mapped[BatchJob] = relationship(back_populates="items")
