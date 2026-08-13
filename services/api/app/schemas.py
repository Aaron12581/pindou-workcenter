from datetime import datetime

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)


class AssetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    sequence_no: int
    role: str
    parent_asset_id: str | None = None
    archived: bool = False
    original_name: str
    mime_type: str
    file_size: int
    sha256: str
    created_at: datetime


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    owner_id: str
    name: str
    status: str
    current_stage: str
    archived: bool = False
    created_at: datetime
    updated_at: datetime
    assets: list[AssetRead] = []


class ProjectList(BaseModel):
    items: list[ProjectRead]
    total: int


class BackupImportRead(BaseModel):
    project: ProjectRead
    source_project_id: str


class PatternGenerate(BaseModel):
    source_asset_id: str
    board_layout: str = "quad"
    color_mode: str = "standard"
    # This is deliberately a user choice rather than an automatic fallback.
    # A pattern made by the local simplifier and one authored by an image model
    # have different strengths and must stay comparable in project history.
    generation_mode: Literal["local", "model_direct"] = "local"


class PatternRead(BaseModel):
    id: str
    project_id: str
    source_asset_id: str
    board_layout: str
    color_mode: str
    palette_version: str
    pattern: dict
    created_at: datetime


class PatternUpdate(BaseModel):
    pattern: dict
    expected_revision: int = Field(ge=0)


class PatternVersionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    note: str = Field(default="", max_length=500)
    expected_revision: int = Field(ge=0)


class PatternVersionRead(BaseModel):
    id: str
    version_no: int
    name: str
    note: str
    source_revision: int
    created_at: datetime
    pattern: dict | None = None


class PatternVersionList(BaseModel):
    items: list[PatternVersionRead]
    total: int


class StageVersionCreate(BaseModel):
    snapshot: dict
    name: str = Field(min_length=1, max_length=120)


class StageVersionRead(BaseModel):
    id: str
    stage: str
    version_no: int
    name: str
    created_at: datetime
    snapshot: dict | None = None


class StageVersionList(BaseModel):
    items: list[StageVersionRead]
    total: int


class PatternRestore(BaseModel):
    expected_revision: int = Field(ge=0)


class PatternInspectionRead(BaseModel):
    inspected_revision: int
    summary: dict
    issues: list[dict]


class PatternWatermark(BaseModel):
    enabled: bool = False
    text: str = Field(default="", max_length=100)
    color: str = Field(default="#526c7e", pattern=r"^#[0-9A-Fa-f]{6}$")
    font: str = Field(default="sans", pattern=r"^(sans|serif|bold|mono|rounded|elegant|italic|handwritten)$")
    size: int = Field(default=72, ge=12, le=1600)
    opacity: int = Field(default=55, ge=0, le=100)
    rotation: float = Field(default=0, ge=0, le=360)
    x: float = Field(default=82, ge=0, le=100)
    y: float = Field(default=94, ge=0, le=100)


class PatternExportCreate(BaseModel):
    expected_revision: int = Field(ge=0)
    watermark: PatternWatermark | None = None
    include_mirrored_pattern: bool = False


class PatternExportRead(BaseModel):
    filename: str
    revision: int
    board_count: int
    file_count: int
    total_beads: int
    color_count: int
    size_bytes: int
    download_url: str
    manifest: dict


class AssetRoleUpdate(BaseModel):
    role: str = Field(pattern="^(original|2d_candidate|confirmed_2d)$")


class ArchiveUpdate(BaseModel):
    archived: bool


class TwoDGenerate(BaseModel):
    source_asset_id: str
    crop: dict = {}
    subject_boxes: list[dict] = []
    mask_strokes: list[dict] = []
    subject_mode: Literal["single", "multiple", "primary"] = "single"
    composition: str = "full"
    style: str = "clean polished 2D character illustration"
    outline: str = "automatic darker subject-color outline"
    candidate_mode: Literal["single", "all"] = "all"
    variant: Literal["simplified", "standard", "rich"] = "standard"


class TwoDCandidateRead(BaseModel):
    asset: AssetRead
    source_asset_id: str
    variant: str
    label: str
    detail: str
    recommended: bool
    quality: dict = {}


class TwoDConfirm(BaseModel):
    candidate_asset_id: str


class BatchCreate(BaseModel):
    source_asset_ids: list[str] = Field(min_length=2, max_length=10)
    board_layout: str = "quad"
    color_mode: str = "standard"


class BatchItemRead(BaseModel):
    id: str
    sequence_no: int
    source_asset_id: str
    status: str
    pattern_id: str | None
    error_code: str | None
    confirmed: bool
    attempts: int


class BatchRead(BaseModel):
    id: str
    project_id: str
    status: str
    board_layout: str
    color_mode: str
    created_at: datetime
    updated_at: datetime
    items: list[BatchItemRead]
    summary: dict


class BatchList(BaseModel):
    items: list[BatchRead]
    total: int


class BatchConfirm(BaseModel):
    item_ids: list[str] = Field(min_length=1, max_length=10)
