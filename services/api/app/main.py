import hashlib
import json
import shutil
import tempfile
import zipfile
from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import Path
from uuid import uuid4
from PIL import Image

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import func, inspect, select, text
from sqlalchemy.orm import Session, selectinload

from .config import settings
from .db import Base, engine, get_db
from .models import Asset, BatchItem, BatchJob, Pattern, PatternVersion, Project, StageVersion
from .pattern_engine import generate_pattern, generate_pattern_from_model_grid, generate_pattern_from_model_image
from .pattern_model import planner_status
from .pattern_exporter import build_export_package
from .pattern_inspector import inspect_pattern
from .mard_palette import MARD_STANDARD_PALETTE
from .twod_engine import (
    VARIANTS,
    generate_2d_candidates,
    inspect_candidate,
    prepare_model_source,
)
from .image_model import ModelGenerationError, generate_direct_pattern_image, generate_model_candidates, model_status
from .schemas import (
    ArchiveUpdate, AssetRead, AssetRoleUpdate, BackupImportRead, BatchConfirm, BatchCreate, BatchItemRead, BatchList, BatchRead, PatternExportCreate, PatternExportRead, PatternGenerate, PatternInspectionRead, PatternRead,
    PatternRestore, PatternUpdate, PatternVersionCreate, PatternVersionList,
    PatternVersionRead, ProjectCreate, ProjectList, ProjectRead, TwoDCandidateRead,
    StageVersionCreate, StageVersionList, StageVersionRead,
    TwoDConfirm, TwoDGenerate,
)


BACKUP_FORMAT = "perler-project-backup"
BACKUP_VERSION = 1


def apply_crop(content: bytes, crop: dict) -> bytes:
    if not crop:
        return content
    image = Image.open(BytesIO(content))
    width, height = image.size
    x = max(0.0, min(1.0, float(crop.get("x", 0))))
    y = max(0.0, min(1.0, float(crop.get("y", 0))))
    crop_width = max(0.01, min(1.0 - x, float(crop.get("width", 1))))
    crop_height = max(0.01, min(1.0 - y, float(crop.get("height", 1))))
    box = (round(x * width), round(y * height), round((x + crop_width) * width), round((y + crop_height) * height))
    cropped = image.crop(box)
    output = BytesIO()
    cropped.convert("RGB").save(output, format="JPEG", quality=95)
    return output.getvalue()


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.database_url.startswith("sqlite"):
        Path(settings.database_url.removeprefix("sqlite:///")).parent.mkdir(
            parents=True, exist_ok=True
        )
        Base.metadata.create_all(engine)
        columns = {table: {item["name"] for item in inspect(engine).get_columns(table)} for table in ("projects", "assets")}
        with engine.begin() as connection:
            if "archived" not in columns["projects"]:
                connection.execute(text("ALTER TABLE projects ADD COLUMN archived BOOLEAN NOT NULL DEFAULT 0"))
            if "archived" not in columns["assets"]:
                connection.execute(text("ALTER TABLE assets ADD COLUMN archived BOOLEAN NOT NULL DEFAULT 0"))
            if "parent_asset_id" not in columns["assets"]:
                connection.execute(text("ALTER TABLE assets ADD COLUMN parent_asset_id VARCHAR(36)"))
    settings.storage_root.mkdir(parents=True, exist_ok=True)
    settings.backup_root.mkdir(parents=True, exist_ok=True)
    settings.export_root.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(
    title="拼豆图纸工作台 API",
    version="0.20.47",
    description="正式 2D 直连大模型分板图纸生成、编辑、版本、检查与导出",
    lifespan=lifespan,
)


@app.get("/api/v1/bead-brands/{brand_code}/colors")
def list_brand_colors(brand_code: str) -> dict:
    """Expose the complete read-only official palette for the editor picker."""
    if brand_code.upper() != "MARD":
        raise HTTPException(status_code=404, detail={"code": "BEAD_BRAND_NOT_FOUND"})
    return {"brand": "MARD", "paletteVersion": "official-v1", "colors": [{"code": color.code, "value": color.hex} for color in MARD_STANDARD_PALETTE]}
app.add_middleware(
    CORSMiddleware,
    # Desktop mode serves the bundled renderer from an ephemeral loopback
    # port.  The API itself remains bound to 127.0.0.1, so accepting that
    # renderer origin avoids baking a fragile port number into the app.
    allow_origins=["*"] if settings.desktop_mode else list(settings.cors_origins),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def owner_id(x_owner_id: str | None = Header(default=None)) -> str:
    # MVP 单用户边界。接入正式登录后由已验证的身份令牌提供该值。
    return x_owner_id or "00000000-0000-0000-0000-000000000001"


def load_project(project_id: str, owner: str, db: Session) -> Project:
    project = db.scalar(
        select(Project)
        .where(Project.id == project_id, Project.owner_id == owner)
        .options(selectinload(Project.assets))
    )
    if not project:
        raise HTTPException(status_code=404, detail={"code": "PROJECT_NOT_FOUND"})
    return project


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/model-status")
def read_model_status() -> dict:
    return model_status()


@app.post("/api/v1/projects", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreate,
    db: Session = Depends(get_db),
    owner: str = Depends(owner_id),
) -> Project:
    project = Project(owner_id=owner, name=payload.name.strip())
    db.add(project)
    db.commit()
    return load_project(project.id, owner, db)


@app.get("/api/v1/projects", response_model=ProjectList)
def list_projects(
    archived: bool = False,
    db: Session = Depends(get_db),
    owner: str = Depends(owner_id),
) -> ProjectList:
    projects = list(
        db.scalars(
            select(Project)
            .where(Project.owner_id == owner, Project.archived == archived)
            .options(selectinload(Project.assets))
            .order_by(Project.updated_at.desc())
        ).unique()
    )
    return ProjectList(items=projects, total=len(projects))


@app.patch("/api/v1/projects/{project_id}/archive", response_model=ProjectRead)
def archive_project(project_id: str, payload: ArchiveUpdate, db: Session = Depends(get_db), owner: str = Depends(owner_id)) -> Project:
    project = load_project(project_id, owner, db)
    project.archived = payload.archived
    db.commit()
    return load_project(project_id, owner, db)


@app.patch("/api/v1/projects/{project_id}/assets/{asset_id}/archive", response_model=ProjectRead)
def archive_asset(project_id: str, asset_id: str, payload: ArchiveUpdate, db: Session = Depends(get_db), owner: str = Depends(owner_id)) -> Project:
    project = load_project(project_id, owner, db)
    asset = next((item for item in project.assets if item.id == asset_id), None)
    if not asset:
        raise HTTPException(status_code=404, detail={"code": "ASSET_NOT_FOUND"})
    asset.archived = payload.archived
    if asset.role == "original" and payload.archived:
        for item in project.assets:
            if item.parent_asset_id == asset.id or candidate_source_id(item) == asset.id:
                item.archived = True
    db.commit()
    return load_project(project_id, owner, db)


@app.get("/api/v1/projects/{project_id}", response_model=ProjectRead)
def get_project(
    project_id: str,
    db: Session = Depends(get_db),
    owner: str = Depends(owner_id),
) -> Project:
    return load_project(project_id, owner, db)


def asset_path(asset: Asset) -> Path:
    path = (settings.storage_root / asset.storage_key).resolve()
    root = settings.storage_root.resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(status_code=404, detail={"code": "ASSET_FILE_NOT_FOUND"})
    return path


@app.get("/api/v1/projects/{project_id}/assets/{asset_id}/content")
def read_asset(
    project_id: str,
    asset_id: str,
    db: Session = Depends(get_db),
    owner: str = Depends(owner_id),
) -> FileResponse:
    project = load_project(project_id, owner, db)
    asset = next((item for item in project.assets if item.id == asset_id), None)
    if not asset:
        raise HTTPException(status_code=404, detail={"code": "ASSET_NOT_FOUND"})
    return FileResponse(asset_path(asset), media_type=asset.mime_type, filename=asset.original_name)


@app.patch("/api/v1/projects/{project_id}/assets/{asset_id}/role", response_model=AssetRead)
def update_asset_role(
    project_id: str,
    asset_id: str,
    payload: AssetRoleUpdate,
    db: Session = Depends(get_db),
    owner: str = Depends(owner_id),
) -> Asset:
    project = load_project(project_id, owner, db)
    asset = next((item for item in project.assets if item.id == asset_id), None)
    if not asset:
        raise HTTPException(status_code=404, detail={"code": "ASSET_NOT_FOUND"})
    asset.role = payload.role
    db.commit()
    db.refresh(asset)
    return asset


def candidate_source_id(asset: Asset) -> str | None:
    if asset.parent_asset_id:
        return asset.parent_asset_id
    if asset.role not in {"2d_candidate", "confirmed_2d"}:
        return None
    parts = Path(asset.storage_key).stem.split("__")
    return parts[1] if len(parts) >= 3 and parts[0] == "2d" else None


def candidate_variant(asset: Asset) -> str | None:
    """Read the chosen 2D simplification tier from its stable asset filename."""
    if asset.role not in {"2d_candidate", "confirmed_2d"}:
        return None
    parts = Path(asset.storage_key).stem.split("__")
    variant = parts[2] if len(parts) >= 4 and parts[0] == "2d" else None
    return variant if variant in VARIANTS else None


@app.post(
    "/api/v1/projects/{project_id}/2d-candidates",
    response_model=list[TwoDCandidateRead],
    status_code=status.HTTP_201_CREATED,
)
def create_2d_candidates(
    project_id: str,
    payload: TwoDGenerate,
    db: Session = Depends(get_db),
    owner: str = Depends(owner_id),
) -> list[TwoDCandidateRead]:
    project = load_project(project_id, owner, db)
    source = next((item for item in project.assets if item.id == payload.source_asset_id), None)
    if not source or source.role != "original":
        raise HTTPException(status_code=409, detail={"code": "ORIGINAL_ASSET_REQUIRED"})
    try:
        generated, quality = generate_2d_candidates(asset_path(source).read_bytes(), {
            "crop": payload.crop,
            "subject_boxes": payload.subject_boxes,
            "mask_strokes": payload.mask_strokes,
            "composition": payload.composition,
        })
    except ModelGenerationError as exc:
        raise HTTPException(status_code=422, detail=exc.detail()) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": str(exc)}) from exc

    # Generated 2D images are paid assets. Keep every prior generation as a
    # browsable version; generating a new candidate must not delete or demote
    # the current formal 2D until the user explicitly confirms another one.

    created: list[TwoDCandidateRead] = []
    project_root = settings.storage_root / project.id
    project_root.mkdir(parents=True, exist_ok=True)
    next_sequence = max((item.sequence_no for item in project.assets), default=0)
    for offset, (variant, content) in enumerate(generated.items(), start=1):
        asset_id = str(uuid4())
        storage_name = f"2d__{source.id}__{variant}__{asset_id}.png"
        (project_root / storage_name).write_bytes(content)
        config = VARIANTS[variant]
        asset = Asset(
            id=asset_id,
            project_id=project.id,
            sequence_no=next_sequence + offset,
            role="2d_candidate",
            parent_asset_id=source.id,
            storage_key=f"{project.id}/{storage_name}",
            original_name=f"{Path(source.original_name).stem}_{config['detail']}_2D.png",
            mime_type="image/png",
            file_size=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
        )
        db.add(asset)
        db.flush()
        created.append(TwoDCandidateRead(
            asset=AssetRead.model_validate(asset),
            source_asset_id=source.id,
            variant=variant,
            label=config["label"],
            detail=config["detail"],
            recommended=variant == "standard",
            quality=quality,
        ))
    project.current_stage = "2d_candidate"
    db.commit()
    return created


@app.post(
    "/api/v1/projects/{project_id}/2d-candidates/model",
    response_model=list[TwoDCandidateRead],
    status_code=status.HTTP_201_CREATED,
)
def create_model_2d_candidates(
    project_id: str,
    payload: TwoDGenerate,
    db: Session = Depends(get_db),
    owner: str = Depends(owner_id),
) -> list[TwoDCandidateRead]:
    project = load_project(project_id, owner, db)
    source = next((item for item in project.assets if item.id == payload.source_asset_id), None)
    if not source or source.role != "original":
        raise HTTPException(status_code=409, detail={"code": "ORIGINAL_ASSET_REQUIRED"})
    try:
        generated, quality = generate_model_candidates(prepare_model_source(asset_path(source).read_bytes(), {
            "crop": payload.crop,
            "subject_boxes": payload.subject_boxes,
            "mask_strokes": payload.mask_strokes,
            "composition": payload.composition,
        }), {
            "style": payload.style,
            "outline": payload.outline,
            "candidate_mode": payload.candidate_mode,
            "variant": payload.variant,
            "subject_mode": payload.subject_mode,
        })
    except ModelGenerationError as exc:
        raise HTTPException(status_code=422, detail=exc.detail()) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": str(exc)}) from exc

    # Preserve previous candidates as generation history. Confirmation remains
    # the only action that changes which asset is the formal 2D.
    created: list[TwoDCandidateRead] = []
    project_root = settings.storage_root / project.id
    project_root.mkdir(parents=True, exist_ok=True)
    next_sequence = max((item.sequence_no for item in project.assets), default=0)
    for offset, (variant, content) in enumerate(generated.items(), start=1):
        asset_id = str(uuid4())
        storage_name = f"2d__{source.id}__{variant}__{asset_id}.png"
        (project_root / storage_name).write_bytes(content)
        config = VARIANTS[variant]
        asset = Asset(
            id=asset_id, project_id=project.id, sequence_no=next_sequence + offset,
            role="2d_candidate", parent_asset_id=source.id, storage_key=f"{project.id}/{storage_name}",
            original_name=f"{Path(source.original_name).stem}_{config['detail']}_成品2D.png",
            mime_type="image/png", file_size=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
        )
        db.add(asset)
        db.flush()
        created.append(TwoDCandidateRead(
            asset=AssetRead.model_validate(asset), source_asset_id=source.id,
            variant=variant, label=config["label"], detail=config["detail"],
            recommended=variant == "standard", quality=quality,
        ))
    project.current_stage = "2d_candidate"
    db.commit()
    return created


@app.get(
    "/api/v1/projects/{project_id}/2d-candidates/{source_asset_id}",
    response_model=list[TwoDCandidateRead],
)
def list_2d_candidates(
    project_id: str,
    source_asset_id: str,
    db: Session = Depends(get_db),
    owner: str = Depends(owner_id),
) -> list[TwoDCandidateRead]:
    project = load_project(project_id, owner, db)
    result = []
    for asset in sorted(project.assets, key=lambda item: item.sequence_no, reverse=True):
        if candidate_source_id(asset) != source_asset_id:
            continue
        variant = Path(asset.storage_key).stem.split("__")[2]
        if variant not in VARIANTS:
            continue
        config = VARIANTS[variant]
        result.append(TwoDCandidateRead(
            asset=AssetRead.model_validate(asset), source_asset_id=source_asset_id,
            variant=variant, label=config["label"], detail=config["detail"],
            recommended=variant == "standard",
            quality=inspect_candidate(asset_path(asset).read_bytes()),
        ))
    return result


@app.post(
    "/api/v1/projects/{project_id}/2d-candidates/confirm",
    response_model=AssetRead,
)
def confirm_2d_candidate(
    project_id: str,
    payload: TwoDConfirm,
    db: Session = Depends(get_db),
    owner: str = Depends(owner_id),
) -> Asset:
    project = load_project(project_id, owner, db)
    selected = next((item for item in project.assets if item.id == payload.candidate_asset_id), None)
    if not selected or selected.role not in {"2d_candidate", "confirmed_2d"}:
        raise HTTPException(status_code=409, detail={"code": "TWO_D_CANDIDATE_REQUIRED"})
    selected_path = asset_path(selected)
    selected_bytes = selected_path.read_bytes()
    candidate_quality = inspect_candidate(selected_bytes)
    if not candidate_quality.get("confirmable", False):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "FINAL_2D_GENERATION_REQUIRED",
                "message": "候选尚未达到正式 2D 的最小主体覆盖率，请重新生成或调整构图后重试。",
            },
        )
    source_id = candidate_source_id(selected)
    for asset in project.assets:
        if asset.id != selected.id and asset.role == "confirmed_2d" and candidate_source_id(asset) == source_id:
            for pattern in db.scalars(select(Pattern).where(Pattern.source_asset_id == asset.id)):
                document = json.loads(pattern.pattern_json)
                document["stale"] = True
                document["staleReason"] = "FORMAL_2D_CHANGED"
                pattern.pattern_json = json.dumps(document, ensure_ascii=False)
            asset.role = "2d_candidate"
    selected.role = "confirmed_2d"
    project.current_stage = "board"
    db.commit()
    db.refresh(selected)
    return selected


def pattern_read(pattern: Pattern) -> PatternRead:
    return PatternRead(
        id=pattern.id,
        project_id=pattern.project_id,
        source_asset_id=pattern.source_asset_id,
        board_layout=pattern.board_layout,
        color_mode=pattern.color_mode,
        palette_version=pattern.palette_version,
        pattern=json.loads(pattern.pattern_json),
        created_at=pattern.created_at,
    )


def load_pattern(project_id: str, pattern_id: str, db: Session) -> Pattern:
    pattern = db.scalar(
        select(Pattern).where(Pattern.id == pattern_id, Pattern.project_id == project_id)
    )
    if not pattern:
        raise HTTPException(status_code=404, detail={"code": "PATTERN_NOT_FOUND"})
    return pattern


@app.post(
    "/api/v1/projects/{project_id}/patterns/generate",
    response_model=PatternRead,
    status_code=status.HTTP_201_CREATED,
)
def create_pattern(
    project_id: str,
    payload: PatternGenerate,
    db: Session = Depends(get_db),
    owner: str = Depends(owner_id),
) -> PatternRead:
    project = load_project(project_id, owner, db)
    asset = next((item for item in project.assets if item.id == payload.source_asset_id), None)
    if not asset:
        raise HTTPException(status_code=404, detail={"code": "ASSET_NOT_FOUND"})
    # v0.12.7's pattern page submitted the first project asset, normally the
    # original upload. Preserve the formal-2D gate while resolving the unique
    # confirmed candidate linked to that original for migrated projects.
    if asset.role == "original":
        formal_matches = [
            item
            for item in project.assets
            if item.role == "confirmed_2d" and candidate_source_id(item) == asset.id
        ]
        if len(formal_matches) == 1:
            asset = formal_matches[0]
    if asset.role != "confirmed_2d":
        raise HTTPException(status_code=409, detail={"code": "FORMAL_2D_REQUIRED"})
    try:
        original_id = candidate_source_id(asset)
        original = next((item for item in project.assets if item.id == original_id and item.role == "original"), None)
        source_bytes = asset_path(asset).read_bytes()
        reference_bytes = asset_path(original).read_bytes() if original else None
        model_pattern_image = None
        planning_error = None
        planning_error_message = None
        if payload.generation_mode == "model_direct":
            try:
                model_pattern_image = generate_direct_pattern_image(
                    source_bytes, layout=payload.board_layout, color_mode=payload.color_mode,
                    source_variant=candidate_variant(asset),
                )
            except ModelGenerationError as exc:
                planning_error = exc.code
                planning_error_message = exc.provider_message or "图纸图像模型调用失败。"
                planning_error_detail = exc.detail()
            except Exception as exc:
                planning_error = "PATTERN_MODEL_CALL_FAILED"
                planning_error_message = str(exc)[:300] or "图纸图像模型调用失败。"
                planning_error_detail = {"code": planning_error, "provider_message": planning_error_message}
        # A direct-model request must never masquerade as a successful local
        # pattern.  The user has explicitly chosen the mode, so it has no
        # automatic fallback.
        if planning_error:
            planning_error_detail["message"] = planning_error_message
            raise HTTPException(
                status_code=502,
                detail=planning_error_detail,
            )
        if model_pattern_image is not None:
            generated = generate_pattern_from_model_image(
                model_pattern_image, layout=payload.board_layout, color_mode=payload.color_mode,
                model=model_status()["model"],
            )
        else:
            generated = generate_pattern(
                source_bytes, layout=payload.board_layout, color_mode=payload.color_mode,
                reference_image_bytes=reference_bytes,
            )
        planning = generated["statistics"]["semanticPlanning"]
        planning["requestedMode"] = payload.generation_mode
        planning["used"] = bool(model_pattern_image)
        planning["cacheHit"] = False
        planning["fallback"] = False
        planning["fallbackReason"] = None
        planning["fallbackMessage"] = None
        planning["noEffectiveChange"] = False
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": str(exc)}) from exc
    pattern = Pattern(
        project_id=project.id,
        source_asset_id=asset.id,
        board_layout=payload.board_layout,
        color_mode=payload.color_mode,
        pattern_json=json.dumps(generated, ensure_ascii=False, separators=(",", ":")),
    )
    project.current_stage = "candidate"
    db.add(pattern)
    db.commit()
    db.refresh(pattern)
    return pattern_read(pattern)


@app.get("/api/v1/projects/{project_id}/patterns/{pattern_id}", response_model=PatternRead)
def get_pattern(
    project_id: str,
    pattern_id: str,
    db: Session = Depends(get_db),
    owner: str = Depends(owner_id),
) -> PatternRead:
    load_project(project_id, owner, db)
    return pattern_read(load_pattern(project_id, pattern_id, db))


@app.get("/api/v1/projects/{project_id}/patterns:latest", response_model=PatternRead)
def get_latest_pattern(
    project_id: str,
    source_asset_id: str | None = None,
    db: Session = Depends(get_db),
    owner: str = Depends(owner_id),
) -> PatternRead:
    load_project(project_id, owner, db)
    statement = select(Pattern).where(Pattern.project_id == project_id)
    if source_asset_id:
        statement = statement.where(Pattern.source_asset_id == source_asset_id)
    pattern = db.scalar(
        statement
        .order_by(Pattern.created_at.desc())
        .limit(1)
    )
    if not pattern:
        raise HTTPException(status_code=404, detail={"code": "PATTERN_NOT_FOUND"})
    return pattern_read(pattern)


def validate_edited_pattern(value: dict) -> None:
    required = ("schemaVersion", "width", "height", "boardLayout", "cells", "palette", "statistics")
    if any(key not in value for key in required):
        raise HTTPException(status_code=422, detail={"code": "PATTERN_INVALID"})
    width, height = value["width"], value["height"]
    if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
        raise HTTPException(status_code=422, detail={"code": "PATTERN_INVALID"})
    seen: set[tuple[int, int]] = set()
    for cell in value["cells"]:
        coordinate = (cell.get("x"), cell.get("y"))
        if (
            not all(isinstance(item, int) for item in coordinate)
            or not (0 <= coordinate[0] < width and 0 <= coordinate[1] < height)
            or coordinate in seen
            or not cell.get("colorCode")
            or not cell.get("colorValue")
        ):
            raise HTTPException(status_code=422, detail={"code": "PATTERN_INVALID"})
        seen.add(coordinate)


@app.put("/api/v1/projects/{project_id}/patterns/{pattern_id}", response_model=PatternRead)
def update_pattern(
    project_id: str,
    pattern_id: str,
    payload: PatternUpdate,
    db: Session = Depends(get_db),
    owner: str = Depends(owner_id),
) -> PatternRead:
    project = load_project(project_id, owner, db)
    pattern = load_pattern(project_id, pattern_id, db)
    current = json.loads(pattern.pattern_json)
    current_revision = int(current.get("revision", 0))
    if payload.expected_revision != current_revision:
        raise HTTPException(status_code=409, detail={"code": "PATTERN_VERSION_CONFLICT"})
    validate_edited_pattern(payload.pattern)
    updated = dict(payload.pattern)
    updated["revision"] = current_revision + 1
    pattern.pattern_json = json.dumps(updated, ensure_ascii=False, separators=(",", ":"))
    project.current_stage = "editing"
    db.commit()
    db.refresh(pattern)
    return pattern_read(pattern)


def version_read(version: PatternVersion, include_pattern: bool = False) -> PatternVersionRead:
    return PatternVersionRead(
        id=version.id,
        version_no=version.version_no,
        name=version.name,
        note=version.note,
        source_revision=version.source_revision,
        created_at=version.created_at,
        pattern=json.loads(version.pattern_json) if include_pattern else None,
    )


VALID_VERSION_STAGES = {"twod", "board", "pattern", "editor"}


def stage_version_read(version: StageVersion, include_snapshot: bool = False) -> StageVersionRead:
    return StageVersionRead(
        id=version.id, stage=version.stage, version_no=version.version_no,
        name=version.name, created_at=version.created_at,
        snapshot=json.loads(version.snapshot_json) if include_snapshot else None,
    )


@app.post("/api/v1/projects/{project_id}/stage-versions/{stage}", response_model=StageVersionRead, status_code=status.HTTP_201_CREATED)
def create_stage_version(project_id: str, stage: str, payload: StageVersionCreate, db: Session = Depends(get_db), owner: str = Depends(owner_id)) -> StageVersionRead:
    load_project(project_id, owner, db)
    if stage not in VALID_VERSION_STAGES:
        raise HTTPException(status_code=422, detail={"code": "STAGE_VERSION_INVALID_STAGE"})
    version_no = (db.scalar(select(func.max(StageVersion.version_no)).where(StageVersion.project_id == project_id, StageVersion.stage == stage)) or 0) + 1
    version = StageVersion(project_id=project_id, stage=stage, version_no=version_no, name=payload.name.strip(), snapshot_json=json.dumps(payload.snapshot, ensure_ascii=False, separators=(",", ":")))
    db.add(version); db.commit(); db.refresh(version)
    return stage_version_read(version, include_snapshot=True)


@app.get("/api/v1/projects/{project_id}/stage-versions/{stage}", response_model=StageVersionList)
def list_stage_versions(project_id: str, stage: str, db: Session = Depends(get_db), owner: str = Depends(owner_id)) -> StageVersionList:
    load_project(project_id, owner, db)
    if stage not in VALID_VERSION_STAGES:
        raise HTTPException(status_code=422, detail={"code": "STAGE_VERSION_INVALID_STAGE"})
    items = list(db.scalars(select(StageVersion).where(StageVersion.project_id == project_id, StageVersion.stage == stage).order_by(StageVersion.version_no.desc())))
    return StageVersionList(items=[stage_version_read(item) for item in items], total=len(items))


@app.get("/api/v1/projects/{project_id}/stage-versions/{stage}/{version_id}", response_model=StageVersionRead)
def get_stage_version(project_id: str, stage: str, version_id: str, db: Session = Depends(get_db), owner: str = Depends(owner_id)) -> StageVersionRead:
    load_project(project_id, owner, db)
    version = db.scalar(select(StageVersion).where(StageVersion.id == version_id, StageVersion.project_id == project_id, StageVersion.stage == stage))
    if not version:
        raise HTTPException(status_code=404, detail={"code": "STAGE_VERSION_NOT_FOUND"})
    return stage_version_read(version, include_snapshot=True)


@app.post(
    "/api/v1/projects/{project_id}/patterns/{pattern_id}/versions",
    response_model=PatternVersionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_pattern_version(
    project_id: str,
    pattern_id: str,
    payload: PatternVersionCreate,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8),
    db: Session = Depends(get_db),
    owner: str = Depends(owner_id),
) -> PatternVersionRead:
    load_project(project_id, owner, db)
    pattern = load_pattern(project_id, pattern_id, db)
    snapshot = json.loads(pattern.pattern_json)
    if payload.expected_revision != int(snapshot.get("revision", 0)):
        raise HTTPException(status_code=409, detail={"code": "PATTERN_VERSION_CONFLICT"})
    version_no = (db.scalar(
        select(func.max(PatternVersion.version_no)).where(PatternVersion.pattern_id == pattern.id)
    ) or 0) + 1
    version = PatternVersion(
        pattern_id=pattern.id,
        version_no=version_no,
        name=payload.name.strip(),
        note=payload.note.strip(),
        source_revision=payload.expected_revision,
        pattern_json=json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")),
    )
    db.add(version)
    db.commit()
    db.refresh(version)
    return version_read(version, include_pattern=True)


@app.get(
    "/api/v1/projects/{project_id}/patterns/{pattern_id}/versions",
    response_model=PatternVersionList,
)
def list_pattern_versions(
    project_id: str,
    pattern_id: str,
    db: Session = Depends(get_db),
    owner: str = Depends(owner_id),
) -> PatternVersionList:
    load_project(project_id, owner, db)
    load_pattern(project_id, pattern_id, db)
    items = list(db.scalars(
        select(PatternVersion)
        .where(PatternVersion.pattern_id == pattern_id)
        .order_by(PatternVersion.version_no.desc())
    ))
    return PatternVersionList(items=[version_read(item) for item in items], total=len(items))


@app.get(
    "/api/v1/projects/{project_id}/patterns/{pattern_id}/versions/{version_id}",
    response_model=PatternVersionRead,
)
def get_pattern_version(
    project_id: str,
    pattern_id: str,
    version_id: str,
    db: Session = Depends(get_db),
    owner: str = Depends(owner_id),
) -> PatternVersionRead:
    load_project(project_id, owner, db)
    load_pattern(project_id, pattern_id, db)
    version = db.scalar(select(PatternVersion).where(
        PatternVersion.id == version_id, PatternVersion.pattern_id == pattern_id
    ))
    if not version:
        raise HTTPException(status_code=404, detail={"code": "PATTERN_VERSION_NOT_FOUND"})
    return version_read(version, include_pattern=True)


@app.post(
    "/api/v1/projects/{project_id}/patterns/{pattern_id}/versions/{version_id}/restore",
    response_model=PatternRead,
)
def restore_pattern_version(
    project_id: str,
    pattern_id: str,
    version_id: str,
    payload: PatternRestore,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8),
    db: Session = Depends(get_db),
    owner: str = Depends(owner_id),
) -> PatternRead:
    project = load_project(project_id, owner, db)
    pattern = load_pattern(project_id, pattern_id, db)
    current = json.loads(pattern.pattern_json)
    if payload.expected_revision != int(current.get("revision", 0)):
        raise HTTPException(status_code=409, detail={"code": "PATTERN_VERSION_CONFLICT"})
    version = db.scalar(select(PatternVersion).where(
        PatternVersion.id == version_id, PatternVersion.pattern_id == pattern_id
    ))
    if not version:
        raise HTTPException(status_code=404, detail={"code": "PATTERN_VERSION_NOT_FOUND"})
    restored = json.loads(version.pattern_json)
    restored["revision"] = payload.expected_revision + 1
    pattern.pattern_json = json.dumps(restored, ensure_ascii=False, separators=(",", ":"))
    project.current_stage = "editing"
    db.commit()
    db.refresh(pattern)
    return pattern_read(pattern)


@app.post(
    "/api/v1/projects/{project_id}/patterns/{pattern_id}/inspect",
    response_model=PatternInspectionRead,
)
def inspect_saved_pattern(
    project_id: str,
    pattern_id: str,
    db: Session = Depends(get_db),
    owner: str = Depends(owner_id),
) -> dict:
    load_project(project_id, owner, db)
    pattern = load_pattern(project_id, pattern_id, db)
    return inspect_pattern(json.loads(pattern.pattern_json))


def export_path(project_id: str, pattern_id: str, revision: int) -> Path:
    return settings.export_root / project_id / pattern_id / f"revision-{revision}.zip"


@app.post(
    "/api/v1/projects/{project_id}/patterns/{pattern_id}/exports",
    response_model=PatternExportRead,
    status_code=status.HTTP_201_CREATED,
)
def create_pattern_export(
    project_id: str,
    pattern_id: str,
    payload: PatternExportCreate,
    db: Session = Depends(get_db),
    owner: str = Depends(owner_id),
) -> PatternExportRead:
    project = load_project(project_id, owner, db)
    pattern = load_pattern(project_id, pattern_id, db)
    snapshot = json.loads(pattern.pattern_json)
    revision = int(snapshot.get("revision", 0))
    if payload.expected_revision != revision:
        raise HTTPException(status_code=409, detail={"code": "PATTERN_VERSION_CONFLICT"})
    target = export_path(project_id, pattern_id, revision)
    result = build_export_package(
        project_name=project.name,
        project_id=project.id,
        pattern_id=pattern.id,
        pattern=snapshot,
        destination=target,
        watermark=payload.watermark.model_dump() if payload.watermark else None,
        include_mirrored_pattern=payload.include_mirrored_pattern,
    )
    project.current_stage = "exported"
    db.commit()
    return PatternExportRead(
        **result,
        download_url=f"/api/v1/projects/{project_id}/patterns/{pattern_id}/exports/{revision}/download",
    )


@app.get(
    "/api/v1/projects/{project_id}/patterns/{pattern_id}/exports/{revision}/download"
)
def download_pattern_export(
    project_id: str,
    pattern_id: str,
    revision: int,
    db: Session = Depends(get_db),
    owner: str = Depends(owner_id),
) -> FileResponse:
    project = load_project(project_id, owner, db)
    load_pattern(project_id, pattern_id, db)
    target = export_path(project_id, pattern_id, revision)
    if not target.is_file():
        raise HTTPException(status_code=404, detail={"code": "PATTERN_EXPORT_NOT_FOUND"})
    return FileResponse(
        target,
        media_type="application/zip",
        filename=f"{project.name}_拼豆图纸包_r{revision}.zip",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


def batch_status(items: list[BatchItem]) -> str:
    statuses = {item.status for item in items}
    if not items or statuses == {"failed"}:
        return "failed"
    if "running" in statuses or "queued" in statuses:
        return "running"
    if "failed" in statuses:
        return "partial_failed"
    return "succeeded"


def batch_read(job: BatchJob) -> BatchRead:
    counts: dict[str, int] = {}
    for item in job.items:
        counts[item.status] = counts.get(item.status, 0) + 1
    return BatchRead(
        id=job.id,
        project_id=job.project_id,
        status=job.status,
        board_layout=job.board_layout,
        color_mode=job.color_mode,
        created_at=job.created_at,
        updated_at=job.updated_at,
        items=[
            BatchItemRead(
                id=item.id,
                sequence_no=item.sequence_no,
                source_asset_id=item.source_asset_id,
                status=item.status,
                pattern_id=item.pattern_id,
                error_code=item.error_code,
                confirmed=item.confirmed,
                attempts=item.attempts,
            )
            for item in job.items
        ],
        summary={"total": len(job.items), **counts},
    )


def load_batch(project_id: str, batch_id: str, db: Session) -> BatchJob:
    job = db.scalar(
        select(BatchJob)
        .where(BatchJob.id == batch_id, BatchJob.project_id == project_id)
        .options(selectinload(BatchJob.items))
    )
    if not job:
        raise HTTPException(status_code=404, detail={"code": "BATCH_NOT_FOUND"})
    return job


def run_batch_item(job: BatchJob, item: BatchItem, project: Project, db: Session) -> None:
    snapshot = json.loads(item.input_snapshot_json)
    asset = next((value for value in project.assets if value.id == item.source_asset_id), None)
    item.attempts += 1
    item.status = "running"
    item.error_code = None
    db.flush()
    try:
        if not asset:
            raise ValueError("ASSET_NOT_FOUND")
        generated = generate_pattern(
            asset_path(asset).read_bytes(),
            layout=snapshot["board_layout"],
            color_mode=snapshot["color_mode"],
        )
        pattern = Pattern(
            project_id=project.id,
            source_asset_id=asset.id,
            board_layout=snapshot["board_layout"],
            color_mode=snapshot["color_mode"],
            pattern_json=json.dumps(generated, ensure_ascii=False, separators=(",", ":")),
        )
        db.add(pattern)
        db.flush()
        item.pattern_id = pattern.id
        item.status = "succeeded"
    except (ValueError, OSError) as exc:
        item.status = "failed"
        item.error_code = str(exc) or "BATCH_ITEM_FAILED"


@app.post(
    "/api/v1/projects/{project_id}/batches",
    response_model=BatchRead,
    status_code=status.HTTP_201_CREATED,
)
def create_batch(
    project_id: str,
    payload: BatchCreate,
    db: Session = Depends(get_db),
    owner: str = Depends(owner_id),
) -> BatchRead:
    project = load_project(project_id, owner, db)
    if len(set(payload.source_asset_ids)) != len(payload.source_asset_ids):
        raise HTTPException(status_code=422, detail={"code": "BATCH_ASSET_DUPLICATE"})
    assets = {item.id: item for item in project.assets}
    if any(asset_id not in assets for asset_id in payload.source_asset_ids):
        raise HTTPException(status_code=404, detail={"code": "ASSET_NOT_FOUND"})
    if any(assets[asset_id].role != "confirmed_2d" for asset_id in payload.source_asset_ids):
        raise HTTPException(status_code=409, detail={"code": "FORMAL_2D_REQUIRED"})
    job = BatchJob(
        project_id=project.id,
        status="queued",
        board_layout=payload.board_layout,
        color_mode=payload.color_mode,
    )
    db.add(job)
    db.flush()
    for index, asset_id in enumerate(payload.source_asset_ids, start=1):
        snapshot = {
            "source_asset_id": asset_id,
            "board_layout": payload.board_layout,
            "color_mode": payload.color_mode,
        }
        job.items.append(BatchItem(
            sequence_no=index,
            source_asset_id=asset_id,
            input_snapshot_json=json.dumps(snapshot, separators=(",", ":")),
        ))
    db.flush()
    for item in job.items:
        run_batch_item(job, item, project, db)
    job.status = batch_status(job.items)
    project.current_stage = "candidate"
    db.commit()
    return batch_read(load_batch(project_id, job.id, db))


@app.get("/api/v1/projects/{project_id}/batches", response_model=BatchList)
def list_batches(
    project_id: str,
    db: Session = Depends(get_db),
    owner: str = Depends(owner_id),
) -> BatchList:
    load_project(project_id, owner, db)
    jobs = list(db.scalars(
        select(BatchJob)
        .where(BatchJob.project_id == project_id)
        .options(selectinload(BatchJob.items))
        .order_by(BatchJob.created_at.desc())
    ).unique())
    return BatchList(items=[batch_read(job) for job in jobs], total=len(jobs))


@app.post("/api/v1/projects/{project_id}/batches/{batch_id}/retry", response_model=BatchRead)
def retry_batch(
    project_id: str,
    batch_id: str,
    db: Session = Depends(get_db),
    owner: str = Depends(owner_id),
) -> BatchRead:
    project = load_project(project_id, owner, db)
    job = load_batch(project_id, batch_id, db)
    failed = [item for item in job.items if item.status == "failed"]
    if not failed:
        raise HTTPException(status_code=409, detail={"code": "BATCH_NOT_RETRYABLE"})
    for item in failed:
        run_batch_item(job, item, project, db)
    job.status = batch_status(job.items)
    db.commit()
    return batch_read(load_batch(project_id, batch_id, db))


@app.post("/api/v1/projects/{project_id}/batches/{batch_id}/confirm", response_model=BatchRead)
def confirm_batch_items(
    project_id: str,
    batch_id: str,
    payload: BatchConfirm,
    db: Session = Depends(get_db),
    owner: str = Depends(owner_id),
) -> BatchRead:
    load_project(project_id, owner, db)
    job = load_batch(project_id, batch_id, db)
    selected = set(payload.item_ids)
    if not selected <= {item.id for item in job.items}:
        raise HTTPException(status_code=404, detail={"code": "BATCH_ITEM_NOT_FOUND"})
    for item in job.items:
        if item.id in selected:
            if item.status != "succeeded":
                raise HTTPException(status_code=409, detail={"code": "BATCH_ITEM_NOT_READY"})
            item.confirmed = True
    db.commit()
    return batch_read(load_batch(project_id, batch_id, db))


def batch_export_path(project_id: str, batch_id: str) -> Path:
    return settings.export_root / project_id / "batches" / f"{batch_id}.zip"


@app.post("/api/v1/projects/{project_id}/batches/{batch_id}/export")
def create_batch_export(
    project_id: str,
    batch_id: str,
    db: Session = Depends(get_db),
    owner: str = Depends(owner_id),
) -> dict:
    project = load_project(project_id, owner, db)
    job = load_batch(project_id, batch_id, db)
    confirmed = [item for item in job.items if item.confirmed and item.pattern_id]
    if not confirmed:
        raise HTTPException(status_code=409, detail={"code": "BATCH_CONFIRM_REQUIRED"})
    target = batch_export_path(project_id, batch_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="perler-batch-export-") as temp_dir:
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            manifest = {"format": "perler-batch-export", "version": 1, "batch_id": batch_id, "items": []}
            for item in confirmed:
                pattern = load_pattern(project_id, item.pattern_id, db)
                snapshot = json.loads(pattern.pattern_json)
                item_target = Path(temp_dir) / f"{item.sequence_no:02d}.zip"
                result = build_export_package(
                    project_name=f"{project.name}_{item.sequence_no:02d}",
                    project_id=project.id,
                    pattern_id=pattern.id,
                    pattern=snapshot,
                    destination=item_target,
                )
                archive.write(item_target, f"{item.sequence_no:02d}_{pattern.id}/图纸包.zip")
                manifest["items"].append({
                    "item_id": item.id, "pattern_id": pattern.id,
                    "source_asset_id": item.source_asset_id, "revision": result["revision"],
                })
            archive.writestr("batch-manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return {
        "filename": f"{project.name}_批量图纸包.zip",
        "item_count": len(confirmed),
        "size_bytes": target.stat().st_size,
        "download_url": f"/api/v1/projects/{project_id}/batches/{batch_id}/export/download",
    }


@app.get("/api/v1/projects/{project_id}/batches/{batch_id}/export/download")
def download_batch_export(
    project_id: str,
    batch_id: str,
    db: Session = Depends(get_db),
    owner: str = Depends(owner_id),
) -> FileResponse:
    project = load_project(project_id, owner, db)
    load_batch(project_id, batch_id, db)
    target = batch_export_path(project_id, batch_id)
    if not target.is_file():
        raise HTTPException(status_code=404, detail={"code": "BATCH_EXPORT_NOT_FOUND"})
    return FileResponse(target, media_type="application/zip", filename=f"{project.name}_批量图纸包.zip")


@app.post(
    "/api/v1/projects/{project_id}/assets",
    response_model=list[AssetRead],
    status_code=status.HTTP_201_CREATED,
)
async def upload_assets(
    project_id: str,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    owner: str = Depends(owner_id),
) -> list[Asset]:
    project = load_project(project_id, owner, db)
    if not 1 <= len(files) <= 10:
        raise HTTPException(status_code=422, detail={"code": "ASSET_BATCH_SIZE_INVALID"})
    original_count = sum(item.role == "original" for item in project.assets)
    if original_count + len(files) > 10:
        raise HTTPException(status_code=409, detail={"code": "PROJECT_ASSET_LIMIT_EXCEEDED"})

    project_root = settings.storage_root / owner / project.id
    project_root.mkdir(parents=True, exist_ok=True)
    created: list[Asset] = []
    for offset, upload in enumerate(files, start=1):
        if upload.content_type not in settings.allowed_mime_types:
            raise HTTPException(status_code=415, detail={"code": "ASSET_MIME_UNSUPPORTED"})
        content = await upload.read(settings.max_upload_bytes + 1)
        if not content or len(content) > settings.max_upload_bytes:
            raise HTTPException(status_code=413, detail={"code": "ASSET_SIZE_INVALID"})
        suffix = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}[upload.content_type]
        file_id = str(uuid4())
        destination = project_root / f"{file_id}{suffix}"
        destination.write_bytes(content)
        asset = Asset(
            id=file_id,
            project_id=project.id,
            sequence_no=max((item.sequence_no for item in project.assets), default=0) + offset,
            storage_key=str(destination.relative_to(settings.storage_root)),
            original_name=upload.filename or f"素材{offset}{suffix}",
            mime_type=upload.content_type,
            file_size=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
        )
        db.add(asset)
        created.append(asset)
    db.commit()
    return created


@app.post(
    "/api/v1/projects/{project_id}/assets/confirmed-2d",
    response_model=list[AssetRead],
    status_code=status.HTTP_201_CREATED,
)
async def upload_confirmed_2d_assets(
    project_id: str,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    owner: str = Depends(owner_id),
) -> list[Asset]:
    """Store user-supplied 2D art as a formal, ready-for-board asset.

    These files deliberately have no synthetic "original" parent: importing a
    finished 2D design must not accidentally enter the image-model pipeline.
    """
    project = load_project(project_id, owner, db)
    if not 1 <= len(files) <= 10:
        raise HTTPException(status_code=422, detail={"code": "ASSET_BATCH_SIZE_INVALID"})
    formal_count = sum(item.role == "confirmed_2d" for item in project.assets)
    if formal_count + len(files) > 10:
        raise HTTPException(status_code=409, detail={"code": "PROJECT_ASSET_LIMIT_EXCEEDED"})

    project_root = settings.storage_root / owner / project.id
    project_root.mkdir(parents=True, exist_ok=True)
    created: list[Asset] = []
    for offset, upload in enumerate(files, start=1):
        if upload.content_type not in settings.allowed_mime_types:
            raise HTTPException(status_code=415, detail={"code": "ASSET_MIME_UNSUPPORTED"})
        content = await upload.read(settings.max_upload_bytes + 1)
        if not content or len(content) > settings.max_upload_bytes:
            raise HTTPException(status_code=413, detail={"code": "ASSET_SIZE_INVALID"})
        suffix = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}[upload.content_type]
        file_id = str(uuid4())
        destination = project_root / f"imported2d__{file_id}{suffix}"
        destination.write_bytes(content)
        asset = Asset(
            id=file_id,
            project_id=project.id,
            sequence_no=max((item.sequence_no for item in project.assets), default=0) + offset,
            role="confirmed_2d",
            parent_asset_id=None,
            storage_key=str(destination.relative_to(settings.storage_root)),
            original_name=f"[直导2D] {upload.filename or f'导入2D{offset}{suffix}'}",
            mime_type=upload.content_type,
            file_size=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
        )
        db.add(asset)
        created.append(asset)
    project.current_stage = "board"
    db.commit()
    return created


@app.get("/api/v1/projects/{project_id}/backup")
def export_project_backup(
    project_id: str,
    db: Session = Depends(get_db),
    owner: str = Depends(owner_id),
) -> FileResponse:
    project = load_project(project_id, owner, db)
    backup_path = settings.backup_root / f"{project.id}.perler.zip"
    manifest = {
        "format": BACKUP_FORMAT,
        "version": BACKUP_VERSION,
        "project": {
            "id": project.id,
            "name": project.name,
            "status": project.status,
            "current_stage": project.current_stage,
            "archived": project.archived,
        },
        "assets": [],
        "patterns": [],
        "batches": [],
    }
    with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for asset in project.assets:
            path = asset_path(asset)
            archive_name = f"assets/{asset.id}{path.suffix.lower()}"
            archive.write(path, archive_name)
            manifest["assets"].append(
                {
                    "id": asset.id,
                    "sequence_no": asset.sequence_no,
                    "role": asset.role,
                    "parent_asset_id": asset.parent_asset_id,
                    "archived": asset.archived,
                    "original_name": asset.original_name,
                    "mime_type": asset.mime_type,
                    "file_size": asset.file_size,
                    "sha256": asset.sha256,
                    "archive_path": archive_name,
                    "candidate_source_id": candidate_source_id(asset),
                    "candidate_variant": (
                        Path(asset.storage_key).stem.split("__")[2]
                        if candidate_source_id(asset) else None
                    ),
                }
            )
        patterns = db.scalars(
            select(Pattern)
            .where(Pattern.project_id == project.id)
            .order_by(Pattern.created_at)
        )
        for pattern in patterns:
            saved_versions = list(db.scalars(
                select(PatternVersion)
                .where(PatternVersion.pattern_id == pattern.id)
                .order_by(PatternVersion.version_no)
            ))
            manifest["patterns"].append(
                {
                    "id": pattern.id,
                    "source_asset_id": pattern.source_asset_id,
                    "board_layout": pattern.board_layout,
                    "color_mode": pattern.color_mode,
                    "palette_version": pattern.palette_version,
                    "pattern": json.loads(pattern.pattern_json),
                    "versions": [
                        {
                            "version_no": version.version_no,
                            "name": version.name,
                            "note": version.note,
                            "source_revision": version.source_revision,
                            "pattern": json.loads(version.pattern_json),
                        }
                        for version in saved_versions
                    ],
                }
            )
        jobs = db.scalars(
            select(BatchJob)
            .where(BatchJob.project_id == project.id)
            .options(selectinload(BatchJob.items))
            .order_by(BatchJob.created_at)
        ).unique()
        for job in jobs:
            manifest["batches"].append({
                "id": job.id,
                "status": job.status,
                "board_layout": job.board_layout,
                "color_mode": job.color_mode,
                "items": [{
                    "sequence_no": item.sequence_no,
                    "source_asset_id": item.source_asset_id,
                    "status": item.status,
                    "pattern_id": item.pattern_id,
                    "error_code": item.error_code,
                    "confirmed": item.confirmed,
                    "attempts": item.attempts,
                    "input_snapshot": json.loads(item.input_snapshot_json),
                } for item in job.items],
            })
        archive.writestr(
            "manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2),
        )
    return FileResponse(
        backup_path,
        media_type="application/zip",
        filename=f"{project.name}.perler.zip",
    )


@app.post(
    "/api/v1/project-backups/import",
    response_model=BackupImportRead,
    status_code=status.HTTP_201_CREATED,
)
async def import_project_backup(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    owner: str = Depends(owner_id),
) -> BackupImportRead:
    content = await file.read(settings.max_backup_bytes + 1)
    if not content or len(content) > settings.max_backup_bytes:
        raise HTTPException(status_code=413, detail={"code": "BACKUP_SIZE_INVALID"})

    with tempfile.TemporaryDirectory(prefix="perler-import-") as temp_dir:
        source = Path(temp_dir) / "backup.zip"
        source.write_bytes(content)
        try:
            archive = zipfile.ZipFile(source)
            manifest = json.loads(archive.read("manifest.json"))
        except (zipfile.BadZipFile, KeyError, json.JSONDecodeError):
            raise HTTPException(status_code=422, detail={"code": "BACKUP_INVALID"}) from None
        if (
            manifest.get("format") != BACKUP_FORMAT
            or manifest.get("version") != BACKUP_VERSION
            or not isinstance(manifest.get("assets"), list)
            or len(manifest["assets"]) > 40
        ):
            raise HTTPException(status_code=422, detail={"code": "BACKUP_VERSION_UNSUPPORTED"})

        project_data = manifest.get("project") or {}
        source_project_id = str(project_data.get("id") or "")
        project = Project(
            owner_id=owner,
            name=f"{str(project_data.get('name') or '恢复的项目')[:150]}（恢复）",
            status=str(project_data.get("status") or "draft")[:32],
            current_stage=str(project_data.get("current_stage") or "material")[:32],
            archived=bool(project_data.get("archived", False)),
        )
        db.add(project)
        db.flush()
        project_root = settings.storage_root / owner / project.id
        project_root.mkdir(parents=True, exist_ok=False)
        try:
            restored_asset_ids: dict[str, str] = {
                str(item.get("id") or ""): str(uuid4()) for item in manifest["assets"]
            }
            for offset, item in enumerate(manifest["assets"], start=1):
                archive_path = str(item.get("archive_path") or "")
                if not archive_path.startswith("assets/") or ".." in Path(archive_path).parts:
                    raise ValueError("unsafe archive path")
                payload = archive.read(archive_path)
                if hashlib.sha256(payload).hexdigest() != item.get("sha256"):
                    raise ValueError("checksum mismatch")
                mime_type = str(item.get("mime_type") or "")
                if mime_type not in settings.allowed_mime_types:
                    raise ValueError("unsupported asset type")
                suffix = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}[
                    mime_type
                ]
                asset_id = restored_asset_ids[str(item.get("id") or "")]
                old_source_id = str(item.get("candidate_source_id") or "")
                variant = str(item.get("candidate_variant") or "")
                restored_source_id = restored_asset_ids.get(old_source_id)
                if restored_source_id and variant in VARIANTS:
                    filename = f"2d__{restored_source_id}__{variant}__{asset_id}{suffix}"
                else:
                    filename = f"{asset_id}{suffix}"
                destination = project_root / filename
                destination.write_bytes(payload)
                db.add(
                    Asset(
                        id=asset_id,
                        project_id=project.id,
                        sequence_no=offset,
                        role=str(item.get("role") or "original")[:32],
                        parent_asset_id=restored_asset_ids.get(str(item.get("parent_asset_id") or "")),
                        archived=bool(item.get("archived", False)),
                        storage_key=str(destination.relative_to(settings.storage_root)),
                        original_name=str(item.get("original_name") or destination.name)[:255],
                        mime_type=mime_type,
                        file_size=len(payload),
                        sha256=hashlib.sha256(payload).hexdigest(),
                    )
                )
            restored_pattern_ids: dict[str, str] = {}
            for item in manifest.get("patterns", []):
                source_asset_id = restored_asset_ids.get(str(item.get("source_asset_id") or ""))
                pattern_data = item.get("pattern")
                if not source_asset_id or not isinstance(pattern_data, dict):
                    raise ValueError("invalid pattern backup")
                restored_pattern = Pattern(
                    project_id=project.id,
                    source_asset_id=source_asset_id,
                    board_layout=str(item.get("board_layout") or "")[:32],
                    color_mode=str(item.get("color_mode") or "")[:16],
                    palette_version=str(item.get("palette_version") or "official-v1")[:32],
                    pattern_json=json.dumps(
                        pattern_data, ensure_ascii=False, separators=(",", ":")
                    ),
                )
                db.add(restored_pattern)
                db.flush()
                restored_pattern_ids[str(item.get("id") or "")] = restored_pattern.id
                for version_item in item.get("versions", []):
                    version_pattern = version_item.get("pattern")
                    if not isinstance(version_pattern, dict):
                        raise ValueError("invalid pattern version backup")
                    db.add(PatternVersion(
                        pattern_id=restored_pattern.id,
                        version_no=int(version_item.get("version_no") or 0),
                        name=str(version_item.get("name") or "恢复的版本")[:120],
                        note=str(version_item.get("note") or "")[:500],
                        source_revision=int(version_item.get("source_revision") or 0),
                        pattern_json=json.dumps(
                            version_pattern, ensure_ascii=False, separators=(",", ":")
                        ),
                    ))
            for batch_data in manifest.get("batches", []):
                restored_job = BatchJob(
                    project_id=project.id,
                    status=str(batch_data.get("status") or "failed")[:32],
                    board_layout=str(batch_data.get("board_layout") or "quad")[:32],
                    color_mode=str(batch_data.get("color_mode") or "standard")[:16],
                )
                db.add(restored_job)
                db.flush()
                for item in batch_data.get("items", []):
                    source_asset_id = restored_asset_ids.get(str(item.get("source_asset_id") or ""))
                    if not source_asset_id:
                        raise ValueError("invalid batch asset")
                    snapshot = dict(item.get("input_snapshot") or {})
                    snapshot["source_asset_id"] = source_asset_id
                    restored_job.items.append(BatchItem(
                        sequence_no=int(item.get("sequence_no") or 0),
                        source_asset_id=source_asset_id,
                        status=str(item.get("status") or "failed")[:32],
                        pattern_id=restored_pattern_ids.get(str(item.get("pattern_id") or "")),
                        error_code=(str(item.get("error_code"))[:80] if item.get("error_code") else None),
                        confirmed=bool(item.get("confirmed")),
                        attempts=int(item.get("attempts") or 0),
                        input_snapshot_json=json.dumps(snapshot, separators=(",", ":")),
                    ))
            db.commit()
        except (KeyError, ValueError, zipfile.BadZipFile):
            db.rollback()
            shutil.rmtree(project_root, ignore_errors=True)
            raise HTTPException(status_code=422, detail={"code": "BACKUP_INVALID"}) from None
        restored = load_project(project.id, owner, db)
        return BackupImportRead(project=restored, source_project_id=source_project_id)
