import uuid
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.api.dependencies import WorkspaceContext, current_workspace, envelope, mutation_workspace
from app.api.imports import scoped
from app.api.reports import action_data
from app.automation.notify import FORMATS
from app.automation.scheduler import latest_dataset, next_run, period_preview, run_schedule
from app.core.errors import AppError
from app.db.models import (
    ActionItem,
    DatasetVersion,
    MerchantNote,
    ModelConfig,
    Report,
    ReportSchedule,
    Workspace,
    now,
)
from app.db.session import db_session
from app.ops.audit import audit
from app.providers.adapter import MESSAGES
from app.providers.credentials import seal
from app.providers.egress import ProviderError, normalize_webhook_url
from app.reports.schema import Rules

router = APIRouter(prefix="/api/v1")


class ScheduleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    title: str = Field(default="经营周报", min_length=1, max_length=100)
    dataset_id: uuid.UUID | None = None
    model_config_id: uuid.UUID | None = None
    period_days: int = Field(default=7, ge=1, le=31)
    weekday: int = Field(default=0, ge=0, le=6)
    hour: int = Field(default=8, ge=0, le=23)
    enabled: bool = True
    rules: Rules = Field(default_factory=Rules)
    language: Literal["zh", "en"] = "zh"
    webhook_url: SecretStr | None = Field(default=None, max_length=1000)
    clear_webhook: bool = False
    webhook_format: Literal["generic", "slack", "feishu", "wecom", "dingtalk"] = "generic"


class SchedulePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=100)
    title: str | None = Field(default=None, min_length=1, max_length=100)
    dataset_id: uuid.UUID | None = None
    model_config_id: uuid.UUID | None = None
    period_days: int | None = Field(default=None, ge=1, le=31)
    weekday: int | None = Field(default=None, ge=0, le=6)
    hour: int | None = Field(default=None, ge=0, le=23)
    enabled: bool | None = None
    rules: Rules | None = None
    language: Literal["zh", "en"] | None = None
    webhook_url: SecretStr | None = Field(default=None, max_length=1000)
    clear_webhook: bool = False
    webhook_format: Literal["generic", "slack", "feishu", "wecom", "dingtalk"] | None = None


def schedule_data(db, item, workspace):
    dataset = (
        db.get(DatasetVersion, item.dataset_id)
        if item.dataset_id
        else latest_dataset(db, item.workspace_id)
    )
    return {
        "id": str(item.id),
        "name": item.name,
        "title": item.title,
        "dataset_id": str(item.dataset_id) if item.dataset_id else None,
        "model_config_id": str(item.model_config_id) if item.model_config_id else None,
        "period_days": item.period_days,
        "weekday": item.weekday,
        "hour": item.hour,
        "timezone": workspace.timezone,
        "enabled": item.enabled,
        "rules": item.rules,
        "language": item.language,
        "has_webhook": bool(item.webhook_ciphertext),
        "webhook_format": item.webhook_format,
        "series_id": str(item.series_id) if item.series_id else None,
        "last_report_id": str(item.last_report_id) if item.last_report_id else None,
        "last_run_at": item.last_run_at,
        "next_run_at": item.next_run_at,
        "last_status": item.last_status,
        "next_period": period_preview(dataset, item.period_days) if dataset else None,
        "revision": item.revision,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def apply_schedule(db, item, values, actor, workspace):
    if values.get("dataset_id"):
        scoped(db, DatasetVersion, values["dataset_id"], actor)
    if values.get("model_config_id"):
        scoped(db, ModelConfig, values["model_config_id"], actor)
    for field in (
        "name",
        "title",
        "dataset_id",
        "model_config_id",
        "period_days",
        "weekday",
        "hour",
        "enabled",
        "language",
        "webhook_format",
    ):
        if field in values:
            setattr(item, field, values[field])
    if "rules" in values and values["rules"] is not None:
        item.rules = Rules.model_validate(values["rules"]).model_dump()
    url = values.get("webhook_url")
    if url is not None:
        try:
            normalized = normalize_webhook_url(url.get_secret_value())
        except ProviderError as error:
            raise AppError(422, error.code, MESSAGES[error.code]) from None
        item.webhook_ciphertext, item.webhook_key_version = seal(
            "webhook", item.workspace_id, item.id, normalized
        )
    elif values.get("clear_webhook"):
        item.webhook_ciphertext = item.webhook_key_version = None
    item.next_run_at = (
        next_run(item.weekday, item.hour, workspace.timezone) if item.enabled else None
    )
    item.updated_at = now()


@router.get("/schedules")
def schedules(
    request: Request,
    actor: WorkspaceContext = Depends(current_workspace),
    db: Session = Depends(db_session),
):
    workspace = db.get(Workspace, actor.workspace_id)
    rows = db.scalars(
        select(ReportSchedule)
        .where(ReportSchedule.workspace_id == actor.workspace_id)
        .order_by(ReportSchedule.created_at.desc())
    )
    return envelope(request, [schedule_data(db, r, workspace) for r in rows])


@router.post("/schedules", status_code=201)
def create_schedule(
    payload: ScheduleInput,
    request: Request,
    actor: WorkspaceContext = Depends(mutation_workspace),
    db: Session = Depends(db_session),
):
    if (
        db.scalar(
            select(func.count())
            .select_from(ReportSchedule)
            .where(ReportSchedule.workspace_id == actor.workspace_id)
        )
        >= 20
    ):
        raise AppError(409, "SCHEDULE_LIMIT", "每个店铺最多 20 个定时周报。")
    workspace = db.get(Workspace, actor.workspace_id)
    item = ReportSchedule(id=uuid.uuid4(), workspace_id=actor.workspace_id, revision=1)
    values = dict(payload)
    values["rules"] = payload.rules.model_dump()
    apply_schedule(db, item, values, actor, workspace)
    db.add(item)
    audit(db, actor, "schedule.created", item.id, {"webhook_set": bool(item.webhook_ciphertext)})
    db.commit()
    return envelope(request, schedule_data(db, item, workspace))


@router.patch("/schedules/{schedule_id}")
def patch_schedule(
    schedule_id: uuid.UUID,
    payload: SchedulePatch,
    request: Request,
    actor: WorkspaceContext = Depends(mutation_workspace),
    db: Session = Depends(db_session),
):
    item = scoped(db, ReportSchedule, schedule_id, actor, lock=True)
    if payload.revision != item.revision:
        raise AppError(409, "REVISION_CONFLICT", "配置已变化，请刷新后重试。")
    workspace = db.get(Workspace, actor.workspace_id)
    values = {k: getattr(payload, k) for k in payload.model_fields_set if k != "revision"}
    if "rules" in values and values["rules"] is not None:
        values["rules"] = values["rules"].model_dump()
    apply_schedule(db, item, values, actor, workspace)
    item.revision += 1
    audit(db, actor, "schedule.updated", item.id, {"revision": item.revision})
    db.commit()
    return envelope(request, schedule_data(db, item, workspace))


@router.delete("/schedules/{schedule_id}", status_code=204)
def delete_schedule(
    schedule_id: uuid.UUID,
    actor: WorkspaceContext = Depends(mutation_workspace),
    db: Session = Depends(db_session),
):
    item = scoped(db, ReportSchedule, schedule_id, actor, lock=True)
    db.execute(update(Report).where(Report.schedule_id == item.id).values(schedule_id=None))
    audit(db, actor, "schedule.deleted", item.id)
    db.delete(item)
    db.commit()


@router.post("/schedules/{schedule_id}/run", status_code=202)
def run_now(
    schedule_id: uuid.UUID,
    request: Request,
    actor: WorkspaceContext = Depends(mutation_workspace),
    db: Session = Depends(db_session),
):
    scoped(db, ReportSchedule, schedule_id, actor)
    db.rollback()
    return envelope(request, run_schedule(schedule_id, force=True))


class NoteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_date: date
    end_exclusive: date
    kind: Literal["promotion", "holiday", "stockout", "pricing", "other"] = "other"
    text: str = Field(min_length=1, max_length=300)

    @model_validator(mode="after")
    def valid_range(self):
        if not 1 <= (self.end_exclusive - self.start_date).days <= 366:
            raise ValueError("Note range must be 1 to 366 days")
        if any(ord(c) < 32 and c not in "\n\t" for c in self.text) or not self.text.strip():
            raise ValueError("Invalid note text")
        return self


def note_data(item):
    return {
        "id": str(item.id),
        "start_date": item.start_date.isoformat(),
        "end_exclusive": item.end_exclusive.isoformat(),
        "kind": item.kind,
        "text": item.text,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


@router.get("/notes")
def notes(
    request: Request,
    actor: WorkspaceContext = Depends(current_workspace),
    db: Session = Depends(db_session),
):
    rows = db.scalars(
        select(MerchantNote)
        .where(MerchantNote.workspace_id == actor.workspace_id)
        .order_by(MerchantNote.start_date.desc(), MerchantNote.id)
        .limit(200)
    )
    return envelope(request, [note_data(r) for r in rows])


@router.post("/notes", status_code=201)
def create_note(
    payload: NoteInput,
    request: Request,
    actor: WorkspaceContext = Depends(mutation_workspace),
    db: Session = Depends(db_session),
):
    item = MerchantNote(
        id=uuid.uuid4(),
        workspace_id=actor.workspace_id,
        start_date=payload.start_date,
        end_exclusive=payload.end_exclusive,
        kind=payload.kind,
        text=payload.text.strip(),
    )
    db.add(item)
    audit(db, actor, "note.created", item.id)
    db.commit()
    return envelope(request, note_data(item))


@router.put("/notes/{note_id}")
def update_note(
    note_id: uuid.UUID,
    payload: NoteInput,
    request: Request,
    actor: WorkspaceContext = Depends(mutation_workspace),
    db: Session = Depends(db_session),
):
    item = scoped(db, MerchantNote, note_id, actor, lock=True)
    item.start_date, item.end_exclusive = payload.start_date, payload.end_exclusive
    item.kind, item.text, item.updated_at = payload.kind, payload.text.strip(), now()
    audit(db, actor, "note.updated", item.id)
    db.commit()
    return envelope(request, note_data(item))


@router.delete("/notes/{note_id}", status_code=204)
def delete_note(
    note_id: uuid.UUID,
    actor: WorkspaceContext = Depends(mutation_workspace),
    db: Session = Depends(db_session),
):
    item = scoped(db, MerchantNote, note_id, actor, lock=True)
    audit(db, actor, "note.deleted", item.id)
    db.delete(item)
    db.commit()


class ActionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)
    status: Literal["open", "done", "dismissed"] | None = None
    note: str | None = Field(default=None, max_length=500)


@router.get("/actions")
def actions(
    request: Request,
    status: Literal["open", "done", "dismissed", "all"] = "open",
    offset: int = 0,
    limit: int = 20,
    actor: WorkspaceContext = Depends(current_workspace),
    db: Session = Depends(db_session),
):
    if offset < 0 or not 1 <= limit <= 50:
        raise AppError(422, "INVALID_PAGE", "分页参数无效。")
    stmt = select(ActionItem).where(ActionItem.workspace_id == actor.workspace_id)
    if status != "all":
        stmt = stmt.where(ActionItem.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(
        stmt.order_by(ActionItem.created_at.desc(), ActionItem.position).offset(offset).limit(limit)
    )
    items = []
    for row in rows:
        report = db.get(Report, row.report_id)
        items.append({**action_data(row), "report_title": report.title if report else None})
    return envelope(request, {"total": total, "items": items})


@router.patch("/actions/{action_id}")
def patch_action(
    action_id: uuid.UUID,
    payload: ActionPatch,
    request: Request,
    actor: WorkspaceContext = Depends(mutation_workspace),
    db: Session = Depends(db_session),
):
    item = scoped(db, ActionItem, action_id, actor, lock=True)
    if payload.revision != item.revision:
        raise AppError(409, "REVISION_CONFLICT", "行动项已变化，请刷新后重试。")
    if "status" in payload.model_fields_set and payload.status is not None:
        item.status = payload.status
    if "note" in payload.model_fields_set:
        item.note = (payload.note or "").strip() or None
    item.revision += 1
    item.updated_at = now()
    audit(db, actor, "action.updated", item.id, {"status": item.status})
    db.commit()
    return envelope(request, action_data(item))


__all__ = ["FORMATS", "router"]
