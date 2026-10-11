import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.api.dependencies import (
    WorkspaceContext,
    current_workspace,
    envelope,
)
from app.core.errors import AppError
from app.db import SCHEMA_REVISION
from app.db.models import Job, Workspace
from app.db.session import db_session

router = APIRouter(prefix="/api/v1")


@router.get("/health/live")
def live(request: Request):
    return envelope(request, {"status": "ok", "service": "api"})


@router.get("/health/ready")
def ready(request: Request, db: Session = Depends(db_session)):
    try:
        revision = db.scalar(text("SELECT version_num FROM alembic_version"))
        if revision != SCHEMA_REVISION:
            raise AppError(503, "MIGRATION_REQUIRED", "数据库迁移尚未就绪。", True)
    except AppError:
        raise
    except Exception:
        raise AppError(503, "DATABASE_UNAVAILABLE", "数据库暂不可用。", True) from None
    return envelope(request, {"status": "ready", "schema_revision": SCHEMA_REVISION})


@router.get("/workspace")
def workspace(
    request: Request,
    actor: WorkspaceContext = Depends(current_workspace),
    db: Session = Depends(db_session),
):
    item = db.get(Workspace, actor.workspace_id)
    return envelope(
        request,
        {
            "id": str(item.id),
            "name": item.name,
            "timezone": item.timezone,
            "currency": item.currency,
        },
    )


def job_data(job: Job):
    return {
        "id": str(job.id),
        "type": job.type,
        "status": job.status,
        "attempt": job.attempt,
        "result": job.result,
        "error_code": job.error_code,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


@router.get("/jobs")
def jobs(
    request: Request,
    actor: WorkspaceContext = Depends(current_workspace),
    db: Session = Depends(db_session),
):
    items = db.scalars(
        select(Job)
        .where(Job.workspace_id == actor.workspace_id)
        .order_by(Job.created_at.desc())
        .limit(20)
    ).all()
    return envelope(request, [job_data(item) for item in items])


@router.get("/jobs/{job_id}")
def job_detail(
    job_id: uuid.UUID,
    request: Request,
    actor: WorkspaceContext = Depends(current_workspace),
    db: Session = Depends(db_session),
):
    job = db.scalar(select(Job).where(Job.id == job_id, Job.workspace_id == actor.workspace_id))
    if not job:
        raise AppError(404, "NOT_FOUND", "作业不存在。")
    return envelope(request, job_data(job))
