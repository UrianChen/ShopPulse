import json
import time
import uuid

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import WorkspaceContext, current_workspace, envelope, mutation_workspace
from app.api.imports import scoped
from app.core.errors import AppError
from app.db import session as db_module
from app.db.models import (
    ActionItem,
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
from app.reports import creation
from app.reports.schema import QuestionInput, ReportInput

router = APIRouter(prefix="/api/v1/reports")


def idempotency(db, actor, route, key, payload):
    return creation.idempotency(db, actor.workspace_id, route, key, payload)


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
        "language": report.language,
        "schedule_id": str(report.schedule_id) if report.schedule_id else None,
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
    parent = scoped(db, Report, payload.parent_id, actor, lock=True) if payload.parent_id else None
    report = creation.build_report(
        db, actor.workspace_id, payload, dataset, cached, model, parent, token, hashed
    )
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
                "trace_id": r.trace_id,
                "debug_entries": len(r.debug or []),
                "created_at": r.created_at,
                "completed_at": r.completed_at,
            }
            for r in rows
        ],
    )


def action_data(item):
    return {
        "id": str(item.id),
        "report_id": str(item.report_id),
        "position": item.position,
        "text": item.text,
        "verification_metric": item.verification_metric,
        "review_window": item.review_window,
        "priority": item.priority,
        "effort": item.effort,
        "status": item.status,
        "note": item.note,
        "evaluation": item.evaluation,
        "revision": item.revision,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


@router.get("/{report_id}/actions")
def actions(
    report_id: uuid.UUID,
    request: Request,
    actor: WorkspaceContext = Depends(current_workspace),
    db: Session = Depends(db_session),
):
    scoped(db, Report, report_id, actor)
    rows = db.scalars(
        select(ActionItem).where(ActionItem.report_id == report_id).order_by(ActionItem.position)
    )
    return envelope(request, [action_data(r) for r in rows])


def run_events(run_id, start, deadline_seconds=600, interval=1.0):
    """Server-sent events with the run's trajectory; ends when the run settles."""
    sent, last_ping = start, time.monotonic()
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        with Session(db_module.engine()) as db:
            run = db.get(AgentRun, run_id)
            if run is None:
                return
            steps, status = list(run.steps or []), run.status
        for index in range(sent, len(steps)):
            payload = json.dumps({"index": index, "step": steps[index]}, ensure_ascii=False)
            yield f"event: step\ndata: {payload}\n\n"
        sent = max(sent, len(steps))
        if status not in {"computing", "analyzing"}:
            yield f"event: done\ndata: {json.dumps({'status': status})}\n\n"
            return
        if time.monotonic() - last_ping > 10:
            last_ping = time.monotonic()
            yield ": ping\n\n"
        time.sleep(interval)
    yield "event: timeout\ndata: {}\n\n"


@router.get("/{report_id}/runs/{run_id}/events")
def events(
    report_id: uuid.UUID,
    run_id: uuid.UUID,
    after: int = 0,
    actor: WorkspaceContext = Depends(current_workspace),
    db: Session = Depends(db_session),
):
    scoped(db, Report, report_id, actor)
    run = db.scalar(select(AgentRun).where(AgentRun.id == run_id, AgentRun.report_id == report_id))
    if run is None:
        raise AppError(404, "NOT_FOUND", "运行记录不存在。")
    if after < 0:
        raise AppError(422, "INVALID_PAGE", "参数无效。")
    return StreamingResponse(
        run_events(run.id, after),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
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
