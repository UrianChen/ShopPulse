import shutil
import uuid
from datetime import timedelta
from typing import Literal
from zoneinfo import ZoneInfo

import psutil
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import WorkspaceContext, current_workspace, envelope, mutation_workspace
from app.api.imports import scoped
from app.api.routes import job_data
from app.core.errors import AppError
from app.db.models import AuditEvent, Job, WorkerPulse, Workspace, now
from app.db.session import db_session
from app.ingestion.storage import storage_root
from app.ops import jobs, lifecycle
from app.ops.audit import audit

router = APIRouter(prefix="/api/v1/operations")


class SettingsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=100)
    timezone: str
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    raw_retention_days: int = Field(ge=0, le=3650)
    export_retention_days: int = Field(ge=1, le=3650)

    @field_validator("timezone")
    @classmethod
    def zone(cls, value):
        try:
            ZoneInfo(value)
        except Exception:
            raise ValueError("Unknown timezone") from None
        return value


def settings_data(row):
    return {
        k: getattr(row, k)
        for k in (
            "revision",
            "name",
            "timezone",
            "currency",
            "raw_retention_days",
            "export_retention_days",
        )
    }


@router.get("/settings")
def settings_get(
    request: Request,
    actor: WorkspaceContext = Depends(current_workspace),
    db: Session = Depends(db_session),
):
    return envelope(request, settings_data(db.get(Workspace, actor.workspace_id)))


@router.put("/settings")
def settings_put(
    payload: SettingsInput,
    request: Request,
    actor: WorkspaceContext = Depends(mutation_workspace),
    db: Session = Depends(db_session),
):
    row = db.get(Workspace, actor.workspace_id, with_for_update=True)
    if row.revision != payload.revision:
        raise AppError(409, "REVISION_CONFLICT", "设置已变化，请刷新后重试。")
    for key, value in payload.model_dump(exclude={"revision"}).items():
        setattr(row, key, value)
    row.revision += 1
    audit(db, actor, "workspace.updated", row.id, {"revision": row.revision})
    db.commit()
    return envelope(request, settings_data(row))


@router.get("/status")
def status(
    request: Request,
    actor: WorkspaceContext = Depends(current_workspace),
    db: Session = Depends(db_session),
):
    counts = dict(
        db.execute(
            select(Job.status, func.count())
            .where(Job.workspace_id == actor.workspace_id)
            .group_by(Job.status)
        ).all()
    )
    workers = db.scalars(select(WorkerPulse).order_by(WorkerPulse.heartbeat_at.desc()).limit(20))
    errors = db.execute(
        select(Job.error_code, func.count())
        .where(Job.workspace_id == actor.workspace_id, Job.error_code.is_not(None))
        .group_by(Job.error_code)
    ).all()
    oldest = db.scalar(
        select(func.min(Job.created_at)).where(
            Job.workspace_id == actor.workspace_id, Job.status == "queued"
        )
    )
    disk = shutil.disk_usage(storage_root())
    return envelope(
        request,
        {
            "jobs": counts,
            "oldest_queued_seconds": max(0, int((now() - oldest).total_seconds())) if oldest else 0,
            "failures": dict(errors),
            "disk": {"total_bytes": disk.total, "free_bytes": disk.free},
            "api_rss_bytes": psutil.Process().memory_info().rss,
            "workers": [
                {
                    "id": w.id,
                    "heartbeat_at": w.heartbeat_at,
                    "online": w.heartbeat_at > now() - timedelta(seconds=60),
                    "job_id": w.job_id,
                    "rss_bytes": w.rss_bytes,
                }
                for w in workers
            ],
        },
    )


@router.get("/audit")
def audit_get(
    request: Request,
    offset: int = 0,
    actor: WorkspaceContext = Depends(current_workspace),
    db: Session = Depends(db_session),
):
    if offset < 0:
        raise AppError(422, "INVALID_PAGE", "分页参数无效。")
    rows = db.scalars(
        select(AuditEvent)
        .where(AuditEvent.workspace_id == actor.workspace_id)
        .order_by(AuditEvent.created_at.desc())
        .offset(offset)
        .limit(50)
    )
    return envelope(
        request,
        [
            {k: getattr(r, k) for k in ("id", "action", "target_id", "details", "created_at")}
            for r in rows
        ],
    )


@router.post("/jobs/{job_id}/{action}")
def job_action(
    job_id: uuid.UUID,
    action: Literal["cancel", "retry"],
    request: Request,
    actor: WorkspaceContext = Depends(mutation_workspace),
    db: Session = Depends(db_session),
):
    row = scoped(db, Job, job_id, actor, lock=True)
    if row.error_code == "RESOURCE_DELETED":
        raise AppError(410, "RESOURCE_DELETED", "业务资源已删除。")
    (jobs.cancel if action == "cancel" else jobs.retry)(db, row)
    audit(db, actor, "job." + action, row.id, {"attempt": row.attempt})
    db.commit()
    return envelope(request, job_data(row))


class Confirm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=64, max_length=64)
    confirmation: Literal["确认删除"]


@router.get("/deletion/{kind}/{target}")
def deletion_preview(
    kind: Literal["report", "dataset", "cost", "upload"],
    target: uuid.UUID,
    request: Request,
    actor: WorkspaceContext = Depends(current_workspace),
    db: Session = Depends(db_session),
):
    return envelope(request, lifecycle.deletion_plan(db, actor, kind, target))


@router.post("/deletion/{kind}/{target}")
def deletion_execute(
    kind: Literal["report", "dataset", "cost", "upload"],
    target: uuid.UUID,
    payload: Confirm,
    request: Request,
    actor: WorkspaceContext = Depends(mutation_workspace),
    db: Session = Depends(db_session),
):
    lifecycle.idle_lock(db, actor.workspace_id)
    plan = lifecycle.deletion_plan(db, actor, kind, target)
    if plan["token"] != payload.token:
        raise AppError(409, "IMPACT_CHANGED", "关联数据已变化，请重新预览。")
    files = lifecycle.remove(db, plan)
    audit(db, actor, "resource.deleted", target, {"kind": kind, "counts": plan["counts"]})
    db.commit()
    pending = lifecycle.unlink_files(files, actor.workspace_id)
    return envelope(request, {"deleted": plan["counts"], "pending_files": pending})


@router.get("/cleanup")
def cleanup_preview(
    request: Request,
    actor: WorkspaceContext = Depends(current_workspace),
    db: Session = Depends(db_session),
):
    return envelope(request, lifecycle.cleanup_plan(db, actor.workspace_id))


@router.post("/cleanup")
def cleanup_execute(
    payload: Confirm,
    request: Request,
    actor: WorkspaceContext = Depends(mutation_workspace),
    db: Session = Depends(db_session),
):
    lifecycle.idle_lock(db, actor.workspace_id)
    plan = lifecycle.cleanup_plan(db, actor.workspace_id)
    if plan["token"] != payload.token:
        raise AppError(409, "IMPACT_CHANGED", "清理范围已变化，请重新预览。")
    files = lifecycle.clean(db, plan)
    audit(db, actor, "retention.cleaned", actor.workspace_id, {"counts": plan["counts"]})
    db.commit()
    pending = lifecycle.unlink_files(files, actor.workspace_id)
    return envelope(request, {"cleaned": plan["counts"], "pending_files": pending})
