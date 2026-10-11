import hashlib
import uuid

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.api.dependencies import WorkspaceContext, current_workspace, envelope, mutation_workspace
from app.api.imports import scoped
from app.core.errors import AppError
from app.db.models import (
    AgentRun,
    DatasetVersion,
    Job,
    ModelConfig,
    Report,
    ReportMessage,
    ToolResult,
)
from app.db.session import db_session
from app.metrics.service import request_snapshot
from app.providers.credentials import lock_configs
from app.reports.schema import QuestionInput, ReportInput
from app.reports.tools import digest

router = APIRouter(prefix="/api/v1/reports")


def idempotency(db, actor, route, key, payload):
    token = "report:" + hashlib.sha256(f"{route}:{key}".encode()).hexdigest()
    lock = int(hashlib.sha256(f"{actor.workspace_id}:{token}".encode()).hexdigest()[:15], 16)
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock})
    job = db.scalar(
        select(Job).where(Job.workspace_id == actor.workspace_id, Job.idempotency_key == token)
    )
    hashed = digest(payload)
    if job and job.request_hash != hashed:
        raise AppError(409, "IDEMPOTENCY_CONFLICT", "相同幂等键不能用于不同请求。")
    if job and job.error_code == "RESOURCE_DELETED":
        raise AppError(410, "RESOURCE_DELETED", "此请求关联的数据已删除，请创建新请求。")
    return job, token, hashed


def public(db, report, detail=False):
    job = db.get(Job, report.job_id)
    data = {
        "id": str(report.id),
        "title": report.title,
        "status": report.status,
        "revision": report.revision,
        "series_id": str(report.series_id),
        "parent_id": str(report.parent_id) if report.parent_id else None,
        "dataset_id": str(report.dataset_id),
        "query": report.query,
        "rules": report.rules,
        "model_config_id": str(report.model_config_id) if report.model_config_id else None,
        "job_id": str(report.job_id),
        "job_status": job.status,
        "error_code": job.error_code,
        "generation_mode": report.content.get("generation_mode") if report.content else None,
        "created_at": report.created_at,
    }
    if detail:
        data["content"] = report.content
    return data


@router.post("", status_code=202)
def create(
    payload: ReportInput,
    request: Request,
    idempotency_key: str = Header(min_length=8, max_length=128),
    actor: WorkspaceContext = Depends(mutation_workspace),
    db: Session = Depends(db_session),
):
    data = payload.model_dump(mode="json")
    existing, _, _ = idempotency(db, actor, "create", idempotency_key, data)
    if existing:
        return envelope(
            request, public(db, db.get(Report, uuid.UUID(existing.payload["report_id"])))
        )
    dataset = scoped(db, DatasetVersion, payload.query.dataset_id, actor)
    if payload.parent_id:
        scoped(db, Report, payload.parent_id, actor)
    if payload.model_config_id:
        scoped(db, ModelConfig, payload.model_config_id, actor)
    cached = request_snapshot(
        db, dataset, payload.query
    )  # Commits its own durable metric dependency.
    lock_configs(db)
    existing, token, hashed = idempotency(db, actor, "create", idempotency_key, data)
    if existing:
        return envelope(
            request, public(db, db.get(Report, uuid.UUID(existing.payload["report_id"])))
        )
    model = (
        scoped(db, ModelConfig, payload.model_config_id, actor) if payload.model_config_id else None
    )
    frozen = (
        {
            field: getattr(model, field)
            for field in (
                "name",
                "base_url",
                "model_name",
                "revision",
                "timeout_seconds",
                "token_limit_parameter",
                "product_name_mode",
                "capabilities",
                "consent",
            )
        }
        if model
        else None
    )
    report_id, series_id, revision = uuid.uuid4(), uuid.uuid4(), 1
    if payload.parent_id:
        parent = scoped(db, Report, payload.parent_id, actor, lock=True)
        series_id = parent.series_id
        # Shared config lock serializes all revisions, including branches from different parents.
        revision = (
            db.scalar(select(func.max(Report.revision)).where(Report.series_id == series_id)) + 1
        )
    job = Job(
        workspace_id=actor.workspace_id,
        type="build_report",
        payload={"report_id": str(report_id)},
        request_hash=hashed,
        idempotency_key=token,
    )
    db.add(job)
    db.flush()
    report = Report(
        id=report_id,
        workspace_id=actor.workspace_id,
        dataset_id=dataset.id,
        metric_snapshot_id=cached.id,
        model_config_id=model.id if model else None,
        model_snapshot=frozen,
        series_id=series_id,
        parent_id=payload.parent_id,
        revision=revision,
        title=payload.title,
        query=cached.query,
        rules=payload.rules.model_dump(),
        job_id=job.id,
    )
    db.add(report)
    db.commit()
    return envelope(request, public(db, report))


@router.get("")
def listing(
    request: Request,
    offset: int = 0,
    limit: int = 20,
    actor: WorkspaceContext = Depends(current_workspace),
    db: Session = Depends(db_session),
):
    if offset < 0 or not 1 <= limit <= 50:
        raise AppError(422, "INVALID_PAGE", "分页参数无效。")
    stmt = select(Report).where(Report.workspace_id == actor.workspace_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    return envelope(
        request,
        {
            "total": total,
            "items": [
                public(db, r)
                for r in db.scalars(
                    stmt.order_by(Report.created_at.desc()).offset(offset).limit(limit)
                )
            ],
        },
    )


@router.get("/{report_id}")
def detail(
    report_id: uuid.UUID,
    request: Request,
    actor: WorkspaceContext = Depends(current_workspace),
    db: Session = Depends(db_session),
):
    return envelope(request, public(db, scoped(db, Report, report_id, actor), True))


@router.get("/{report_id}/runs")
def runs(
    report_id: uuid.UUID,
    request: Request,
    actor: WorkspaceContext = Depends(current_workspace),
    db: Session = Depends(db_session),
):
    scoped(db, Report, report_id, actor)
    rows = db.scalars(
        select(AgentRun)
        .where(AgentRun.report_id == report_id)
        .order_by(AgentRun.created_at.desc())
        .limit(50)
    )
    return envelope(
        request,
        [
            {
                "id": str(r.id),
                "job_id": str(r.job_id),
                "attempt": r.attempt,
                "status": r.status,
                "steps": r.steps,
                "usage": r.usage,
                "budgets": r.budgets,
                "error_code": r.error_code,
                "created_at": r.created_at,
                "completed_at": r.completed_at,
            }
            for r in rows
        ],
    )


@router.get("/{report_id}/evidence/{evidence_id}")
def evidence(
    report_id: uuid.UUID,
    evidence_id: uuid.UUID,
    request: Request,
    actor: WorkspaceContext = Depends(current_workspace),
    db: Session = Depends(db_session),
):
    scoped(db, Report, report_id, actor)
    value = db.scalar(
        select(ToolResult).where(ToolResult.id == evidence_id, ToolResult.report_id == report_id)
    )
    if not value:
        raise AppError(404, "NOT_FOUND", "证据不存在于此报告。")
    return envelope(request, value.payload)


@router.post("/{report_id}/messages", status_code=202)
def ask(
    report_id: uuid.UUID,
    payload: QuestionInput,
    request: Request,
    idempotency_key: str = Header(min_length=8, max_length=128),
    actor: WorkspaceContext = Depends(mutation_workspace),
    db: Session = Depends(db_session),
):
    lock_configs(db)
    report = scoped(db, Report, report_id, actor, lock=True)
    if report.status not in {"ready", "ready_with_warnings"}:
        raise AppError(409, "REPORT_NOT_READY", "报告尚未完成。")
    existing, token, hashed = idempotency(
        db, actor, f"ask:{report_id}", idempotency_key, payload.model_dump()
    )
    if existing:
        return envelope(
            request, {"message_id": existing.payload["message_id"], "job_id": str(existing.id)}
        )
    if db.scalar(
        select(ReportMessage.id)
        .where(
            ReportMessage.report_id == report.id, ReportMessage.status.in_(["queued", "running"])
        )
        .limit(1)
    ):
        raise AppError(409, "QUESTION_BUSY", "请等待当前追问完成。")
    sequence = (
        db.scalar(
            select(func.max(ReportMessage.sequence)).where(ReportMessage.report_id == report.id)
        )
        or 0
    ) + 1
    mid = uuid.uuid4()
    job = Job(
        workspace_id=actor.workspace_id,
        type="report_question",
        payload={"report_id": str(report.id), "message_id": str(mid)},
        request_hash=hashed,
        idempotency_key=token,
    )
    db.add(job)
    db.flush()
    db.add(
        ReportMessage(
            id=mid, report_id=report.id, sequence=sequence, question=payload.question, job_id=job.id
        )
    )
    db.commit()
    return envelope(request, {"message_id": str(mid), "job_id": str(job.id)})


@router.get("/{report_id}/messages")
def messages(
    report_id: uuid.UUID,
    request: Request,
    offset: int = 0,
    limit: int = 20,
    actor: WorkspaceContext = Depends(current_workspace),
    db: Session = Depends(db_session),
):
    scoped(db, Report, report_id, actor)
    if offset < 0 or not 1 <= limit <= 50:
        raise AppError(422, "INVALID_PAGE", "分页参数无效。")
    stmt = select(ReportMessage).where(ReportMessage.report_id == report_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(ReportMessage.sequence.desc()).offset(offset).limit(limit))
    return envelope(
        request,
        {
            "total": total,
            "items": [
                {
                    "id": str(m.id),
                    "sequence": m.sequence,
                    "question": m.question,
                    "status": m.status,
                    "answer": m.answer,
                    "created_at": m.created_at,
                }
                for m in rows
            ],
        },
    )
