import uuid
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import WorkspaceContext, current_workspace, envelope, mutation_workspace
from app.api.imports import scoped
from app.api.reports import idempotency
from app.core.errors import AppError
from app.db.models import ExportArtifact, Job, Report, Workspace, now
from app.db.session import db_session
from app.ingestion.storage import object_path
from app.ops.audit import audit

router = APIRouter(prefix="/api/v1")


class ExportInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: Literal["html", "markdown", "pdf"]


def public(row):
    return {
        k: getattr(row, k)
        for k in (
            "id",
            "report_id",
            "job_id",
            "format",
            "status",
            "sha256",
            "size_bytes",
            "error_code",
            "expires_at",
            "created_at",
        )
    }


@router.post("/reports/{report_id}/exports", status_code=202)
def create(
    report_id: uuid.UUID,
    payload: ExportInput,
    request: Request,
    idempotency_key: str = Header(min_length=8, max_length=128),
    actor: WorkspaceContext = Depends(mutation_workspace),
    db: Session = Depends(db_session),
):
    report = scoped(db, Report, report_id, actor, lock=True)
    if report.status not in {"ready", "ready_with_warnings"}:
        raise AppError(409, "REPORT_NOT_READY", "报告尚未完成。")
    existing, key, hashed = idempotency(
        db, actor, f"export:{report_id}", idempotency_key, payload.model_dump()
    )
    if existing:
        row = db.get(ExportArtifact, uuid.UUID(existing.payload["export_id"]))
        if not row:
            raise AppError(410, "EXPORT_DELETED", "导出已删除，请使用新的请求键重新生成。")
        return envelope(request, public(row))
    eid = uuid.uuid4()
    job = Job(
        workspace_id=report.workspace_id,
        type="export_report",
        payload={"export_id": str(eid)},
        idempotency_key=key,
        request_hash=hashed,
    )
    db.add(job)
    db.flush()
    row = ExportArtifact(
        id=eid,
        workspace_id=report.workspace_id,
        report_id=report.id,
        job_id=job.id,
        format=payload.format,
        expires_at=now()
        + timedelta(days=db.get(Workspace, report.workspace_id).export_retention_days),
    )
    db.add(row)
    audit(db, actor, "export.created", eid, {"format": payload.format})
    db.commit()
    return envelope(request, public(row))


@router.get("/reports/{report_id}/exports")
def listing(
    report_id: uuid.UUID,
    request: Request,
    actor: WorkspaceContext = Depends(current_workspace),
    db: Session = Depends(db_session),
):
    scoped(db, Report, report_id, actor)
    rows = db.scalars(
        select(ExportArtifact)
        .where(ExportArtifact.report_id == report_id)
        .order_by(ExportArtifact.created_at.desc())
        .limit(50)
    )
    return envelope(request, [public(row) for row in rows])


@router.get("/exports/{export_id}/download")
def download(
    export_id: uuid.UUID,
    actor: WorkspaceContext = Depends(current_workspace),
    db: Session = Depends(db_session),
):
    row = scoped(db, ExportArtifact, export_id, actor)
    if row.status != "ready" or row.expires_at <= now() or not row.storage_key:
        raise AppError(410, "EXPORT_UNAVAILABLE", "导出未完成或已过期，请重新生成。")
    path = object_path(row.storage_key)
    if not path.is_file():
        raise AppError(410, "EXPORT_UNAVAILABLE", "导出文件已清理，请重新生成。")
    suffix, mime = {
        "html": ("html", "text/html"),
        "markdown": ("zip", "application/zip"),
        "pdf": ("pdf", "application/pdf"),
    }[row.format]
    return FileResponse(
        path,
        media_type=mime,
        filename=f"ShopPulse-{row.report_id}.{suffix}",
        headers={"Content-Security-Policy": "sandbox; default-src 'none'"},
    )
