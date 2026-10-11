import hashlib
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import WorkspaceContext, current_workspace, envelope, mutation_workspace
from app.core.config import ROOT, settings
from app.core.errors import AppError
from app.db.models import (
    CostRow,
    CostVersion,
    DatasetVersion,
    ImportDraft,
    OrderLine,
    Upload,
    ValidationIssue,
    Workspace,
)
from app.db.session import db_session
from app.ingestion.schema import ImportConfig, MappingRequest, ResolutionRequest, RevisionRequest
from app.ingestion.service import schedule
from app.ingestion.storage import object_path

router = APIRouter(prefix="/api/v1")


@router.get("/samples/{filename}")
def sample_file(filename: str, actor: WorkspaceContext = Depends(current_workspace)):
    if filename not in {
        "orders.csv",
        "orders.xlsx",
        "costs.csv",
        "orders_errors.csv",
        "costs_overlap.csv",
    }:
        raise AppError(404, "NOT_FOUND", "样例不存在。")
    return FileResponse(ROOT / "samples" / filename, filename=filename)


def scoped(db, model, item_id, actor, lock=False):
    query = select(model).where(model.id == item_id, model.workspace_id == actor.workspace_id)
    item = db.scalar(query.with_for_update() if lock else query)
    if not item:
        raise AppError(404, "NOT_FOUND", "资源不存在。")
    return item


def draft_data(item):
    return {
        "id": str(item.id),
        "upload_id": str(item.upload_id),
        "name": item.name,
        "kind": item.kind,
        "revision": item.revision,
        "config": item.config,
        "resolutions": item.resolutions,
        "status": item.status,
        "validated_revision": item.validated_revision,
        "summary": item.summary,
        "published_id": str(item.published_id) if item.published_id else None,
        "error_message": item.error_message,
        "created_at": item.created_at,
    }


def revision_guard(draft, expected):
    if draft.revision != expected or draft.status in {"published", "publishing"}:
        raise AppError(
            409, "IMPORT_REVISION_CONFLICT", "导入版本已变化或已发布，请刷新；需要变更时新建导入。"
        )


@router.post("/uploads", status_code=202)
def upload_file(
    request: Request,
    file: UploadFile = File(),
    kind: Literal["orders", "costs"] = Form(),
    actor: WorkspaceContext = Depends(mutation_workspace),
    db: Session = Depends(db_session),
):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".csv", ".xlsx"}:
        raise AppError(422, "FILE_TYPE_REJECTED", "仅支持 CSV 和不含宏的 XLSX。")
    allowed = (
        {"text/csv", "text/plain", "application/vnd.ms-excel", "application/octet-stream"}
        if suffix == ".csv"
        else {
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/octet-stream",
        }
    )
    if file.content_type not in allowed:
        raise AppError(422, "FILE_TYPE_REJECTED", "文件 MIME 类型与扩展名不一致。")
    upload_id = uuid.uuid4()
    key = f"{actor.workspace_id}/uploads/{upload_id}/source{suffix}"
    path = object_path(key)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    digest, size = hashlib.sha256(), 0
    try:
        with path.open("xb") as target:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > settings().max_upload_mib * 1024 * 1024:
                    raise AppError(413, "FILE_TOO_LARGE", "文件超过上传限制，请拆分。")
                digest.update(chunk)
                target.write(chunk)
        with path.open("rb") as source:
            signature = source.read(4)
        if (
            not size
            or (suffix == ".xlsx" and signature[:2] != b"PK")
            or (suffix == ".csv" and signature.startswith((b"PK", b"\xd0\xcf", b"\x00")))
        ):
            raise AppError(422, "FILE_SIGNATURE_INVALID", "文件为空或文件签名与类型不符。")
        item = Upload(
            id=upload_id,
            workspace_id=actor.workspace_id,
            storage_key=key,
            original_name=Path(file.filename.replace("\\", "/")).name[:255],
            sha256=digest.hexdigest(),
            size_bytes=size,
            kind=kind,
            status="parsing",
        )
        db.add(item)
        job = schedule(db, actor.workspace_id, "parse_upload", {"upload_id": str(upload_id)})
        db.commit()
    except Exception:
        db.rollback()
        path.unlink(missing_ok=True)
        raise
    finally:
        file.file.close()
    return envelope(request, {"upload_id": str(item.id), "job_id": str(job.id)})


@router.get("/uploads/{upload_id}")
def get_upload(
    upload_id: uuid.UUID,
    request: Request,
    actor: WorkspaceContext = Depends(current_workspace),
    db: Session = Depends(db_session),
):
    item = scoped(db, Upload, upload_id, actor)
    return envelope(
        request,
        {
            "id": str(item.id),
            "name": item.original_name,
            "kind": item.kind,
            "status": item.status,
            "sha256": item.sha256,
            "size_bytes": item.size_bytes,
            "metadata": item.metadata_json,
            "source_available": item.source_deleted_at is None
            and object_path(item.storage_key).exists(),
            "source_deleted_at": item.source_deleted_at,
            "error_message": item.error_message,
        },
    )


class NewImport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    upload_id: uuid.UUID
    name: str = Field(min_length=1, max_length=120)


@router.post("/imports", status_code=201)
def new_import(
    payload: NewImport,
    request: Request,
    actor: WorkspaceContext = Depends(mutation_workspace),
    db: Session = Depends(db_session),
):
    upload = scoped(db, Upload, payload.upload_id, actor)
    if upload.status not in {"ready", "failed"}:
        raise AppError(409, "UPLOAD_NOT_READY", "请等待文件预览任务完成。")
    if upload.source_deleted_at:
        raise AppError(410, "SOURCE_EXPIRED", "原文件已清理，请重新上传。")
    workspace = db.get(Workspace, actor.workspace_id)
    metadata = upload.metadata_json or {}
    config = ImportConfig(
        sheet_name=metadata.get("sheet_name"),
        columns={k: v["column"] for k, v in metadata.get("suggestions", {}).items()},
    ).model_dump(mode="json")
    config["options"].update(timezone=workspace.timezone, currency=workspace.currency)
    item = ImportDraft(
        workspace_revision=workspace.revision,
        workspace_id=actor.workspace_id,
        upload_id=upload.id,
        name=payload.name,
        kind=upload.kind,
        config=config,
    )
    db.add(item)
    db.commit()
    return envelope(request, draft_data(item))


@router.get("/imports")
def list_imports(
    request: Request,
    actor: WorkspaceContext = Depends(current_workspace),
    db: Session = Depends(db_session),
):
    rows = db.scalars(
        select(ImportDraft)
        .where(ImportDraft.workspace_id == actor.workspace_id)
        .order_by(ImportDraft.created_at.desc())
        .limit(100)
    ).all()
    return envelope(request, [draft_data(item) for item in rows])


@router.get("/imports/{import_id}")
def get_import(
    import_id: uuid.UUID,
    request: Request,
    actor: WorkspaceContext = Depends(current_workspace),
    db: Session = Depends(db_session),
):
    return envelope(request, draft_data(scoped(db, ImportDraft, import_id, actor)))


@router.put("/imports/{import_id}/mapping")
def save_mapping(
    import_id: uuid.UUID,
    payload: MappingRequest,
    request: Request,
    actor: WorkspaceContext = Depends(mutation_workspace),
    db: Session = Depends(db_session),
):
    item = scoped(db, ImportDraft, import_id, actor, True)
    revision_guard(item, payload.expected_revision)
    if payload.config.cost_version_id:
        scoped(db, CostVersion, payload.config.cost_version_id, actor)
    item.config = payload.config.model_dump(mode="json")
    item.revision += 1
    item.resolutions = {}
    item.validated_revision = None
    item.summary = None
    item.status = "mapping_required"
    item.error_message = None
    db.commit()
    return envelope(request, draft_data(item))


@router.put("/imports/{import_id}/resolutions")
def resolve(
    import_id: uuid.UUID,
    payload: ResolutionRequest,
    request: Request,
    actor: WorkspaceContext = Depends(mutation_workspace),
    db: Session = Depends(db_session),
):
    item = scoped(db, ImportDraft, import_id, actor, True)
    revision_guard(item, payload.expected_revision)
    if item.status == "validating" or item.validated_revision != item.revision:
        raise AppError(409, "VALIDATION_REQUIRED", "请先校验当前配置。")
    allowed = set(
        db.scalars(
            select(ValidationIssue.code).where(
                ValidationIssue.import_id == item.id,
                ValidationIssue.revision == item.revision,
                ValidationIssue.severity != "error",
            )
        )
    )
    if set(payload.acknowledged_codes) - allowed or any(r < 1 for r in payload.excluded_rows):
        raise AppError(422, "INVALID_RESOLUTION", "确认规则或排除行号不属于当前校验结果。")
    item.resolutions = payload.model_dump(exclude={"expected_revision"})
    item.revision += 1
    item.status = "mapping_required"
    item.validated_revision = None
    item.summary = None
    db.commit()
    return envelope(request, draft_data(item))


@router.post("/imports/{import_id}/validate", status_code=202)
def validate_import(
    import_id: uuid.UUID,
    payload: RevisionRequest,
    request: Request,
    actor: WorkspaceContext = Depends(mutation_workspace),
    db: Session = Depends(db_session),
):
    item = scoped(db, ImportDraft, import_id, actor, True)
    revision_guard(item, payload.expected_revision)
    if item.status == "validating":
        raise AppError(409, "VALIDATION_IN_PROGRESS", "当前修订正在校验，请等待完成。")
    item.status = "validating"
    job = schedule(
        db,
        actor.workspace_id,
        "validate_import",
        {"import_id": str(item.id), "revision": item.revision},
    )
    db.commit()
    return envelope(request, {"job_id": str(job.id)})


@router.get("/imports/{import_id}/issues")
def issues(
    import_id: uuid.UUID,
    request: Request,
    offset: int = 0,
    limit: int = 100,
    actor: WorkspaceContext = Depends(current_workspace),
    db: Session = Depends(db_session),
):
    item = scoped(db, ImportDraft, import_id, actor)
    if offset < 0 or not 1 <= limit <= 200:
        raise AppError(422, "INVALID_PAGE", "分页参数无效。")
    query = select(ValidationIssue).where(
        ValidationIssue.import_id == item.id, ValidationIssue.revision == item.validated_revision
    )
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    found = db.scalars(
        query.order_by(ValidationIssue.row_number, ValidationIssue.code).offset(offset).limit(limit)
    ).all()
    return envelope(
        request,
        {
            "total": total,
            "items": [
                {
                    "code": i.code,
                    "severity": i.severity,
                    "row_number": i.row_number,
                    "field": i.field,
                    "message": i.message,
                    "acknowledged": i.acknowledged,
                }
                for i in found
            ],
        },
    )


@router.post("/imports/{import_id}/publish", status_code=202)
def publish_import(
    import_id: uuid.UUID,
    payload: RevisionRequest,
    request: Request,
    actor: WorkspaceContext = Depends(mutation_workspace),
    db: Session = Depends(db_session),
):
    item = scoped(db, ImportDraft, import_id, actor, True)
    revision_guard(item, payload.expected_revision)
    if item.status != "ready" or item.validated_revision != item.revision:
        raise AppError(409, "VALIDATION_REQUIRED", "请先解决阻断问题、确认警告并校验当前修订。")
    item.status = "publishing"
    job = schedule(
        db,
        actor.workspace_id,
        "publish_dataset",
        {"import_id": str(item.id), "revision": item.revision},
    )
    db.commit()
    return envelope(request, {"job_id": str(job.id)})


def version_data(v):
    return {
        "id": str(v.id),
        "name": v.name,
        "row_count": v.row_count,
        "created_at": v.created_at,
        "snapshot": v.snapshot,
        "summary": getattr(v, "summary", None),
    }


def source_data(db, version):
    draft = db.get(ImportDraft, version.import_id)
    upload = db.get(Upload, draft.upload_id)
    return {
        "upload_id": str(upload.id),
        "source_available": upload.source_deleted_at is None,
        "source_deleted_at": upload.source_deleted_at,
    }


@router.get("/cost-versions")
def cost_versions(
    request: Request,
    actor: WorkspaceContext = Depends(current_workspace),
    db: Session = Depends(db_session),
):
    values = db.scalars(
        select(CostVersion)
        .where(CostVersion.workspace_id == actor.workspace_id)
        .order_by(CostVersion.created_at.desc())
        .limit(100)
    )
    return envelope(request, [version_data(v) for v in values])


@router.get("/datasets")
def datasets(
    request: Request,
    actor: WorkspaceContext = Depends(current_workspace),
    db: Session = Depends(db_session),
):
    values = db.scalars(
        select(DatasetVersion)
        .where(DatasetVersion.workspace_id == actor.workspace_id)
        .order_by(DatasetVersion.created_at.desc())
        .limit(100)
    )
    return envelope(request, [version_data(v) for v in values])


@router.get("/cost-versions/{version_id}")
def cost_version_detail(
    version_id: uuid.UUID,
    request: Request,
    actor: WorkspaceContext = Depends(current_workspace),
    db: Session = Depends(db_session),
):
    version = scoped(db, CostVersion, version_id, actor)
    rows = db.scalars(
        select(CostRow)
        .where(CostRow.version_id == version.id)
        .order_by(CostRow.sku, CostRow.effective_from)
        .limit(20)
    )
    return envelope(
        request,
        {
            **version_data(version),
            **source_data(db, version),
            "preview": [
                {
                    "sku": r.sku,
                    "unit_cost": str(r.unit_cost),
                    "currency": r.currency,
                    "effective_from": r.effective_from.isoformat(),
                    "effective_to": r.effective_to.isoformat() if r.effective_to else None,
                }
                for r in rows
            ],
        },
    )


@router.get("/datasets/{version_id}")
def dataset(
    version_id: uuid.UUID,
    request: Request,
    actor: WorkspaceContext = Depends(current_workspace),
    db: Session = Depends(db_session),
):
    version = scoped(db, DatasetVersion, version_id, actor)
    rows = db.scalars(
        select(OrderLine)
        .where(OrderLine.dataset_id == version.id)
        .order_by(OrderLine.source_row_number)
        .limit(20)
    )
    return envelope(
        request,
        {
            **version_data(version),
            **source_data(db, version),
            "preview": [
                {
                    "source_row_number": r.source_row_number,
                    "order_id": r.order_id,
                    "sku": r.sku,
                    "quantity": r.quantity,
                    "line_paid_minor": r.line_paid_minor,
                    "line_refund_minor": r.line_refund_minor,
                    "unit_cost": str(r.unit_cost) if r.unit_cost is not None else None,
                }
                for r in rows
            ],
        },
    )
