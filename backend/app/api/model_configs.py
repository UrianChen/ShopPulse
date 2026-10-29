import uuid
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, model_validator
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.api.dependencies import WorkspaceContext, current_workspace, envelope, mutation_workspace
from app.api.imports import scoped
from app.core.errors import AppError
from app.db.models import Job, ModelConfig, Report, ReportMessage, ReportSchedule, now
from app.db.session import db_session
from app.ingestion.service import schedule
from app.ops.audit import audit
from app.providers.adapter import MESSAGES
from app.providers.credentials import encrypt, lock_configs
from app.providers.egress import ProviderError, normalize_url

router = APIRouter(prefix="/api/v1/model-configs")


class ModelInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    base_url: str = Field(min_length=1, max_length=500)
    model_name: str = Field(min_length=1, max_length=200)
    protocol: Literal["openai_chat", "openai_responses", "anthropic_messages"] = "openai_chat"
    timeout_seconds: int = Field(default=45, ge=5, le=300)
    token_limit_parameter: Literal["none", "max_tokens", "max_completion_tokens"] = "none"
    product_name_mode: Literal["sku_only", "include_names"] = "sku_only"
    is_default: bool = False
    consent: Literal[True]
    api_key: SecretStr | None = Field(default=None, max_length=4096)
    clear_api_key: bool = False
    revision: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_input(self):
        if (
            not self.name.strip()
            or not self.model_name.strip()
            or (self.clear_api_key and "api_key" in self.model_fields_set)
            or ("api_key" in self.model_fields_set and self.api_key is None)
        ):
            raise ValueError("Invalid configuration")
        if self.api_key is not None:
            key = self.api_key.get_secret_value()
            if not key or any(ord(char) < 33 or ord(char) > 126 for char in key):
                raise ValueError("Invalid credential")
        return self


def public(item, db):
    job = db.get(Job, item.test_job_id) if item.test_job_id else None
    return {
        "id": str(item.id),
        "name": item.name,
        "base_url": item.base_url,
        "model_name": item.model_name,
        "protocol": item.protocol,
        "revision": item.revision,
        "is_default": item.is_default,
        "timeout_seconds": item.timeout_seconds,
        "token_limit_parameter": item.token_limit_parameter,
        "product_name_mode": item.product_name_mode,
        "consent": item.consent,
        "consent_current": consent_current(item),
        "has_api_key": bool(item.credential_ciphertext),
        "capabilities": item.capabilities,
        "tested_at": item.tested_at,
        "test_job_id": str(item.test_job_id) if item.test_job_id else None,
        "test_status": job.status if job else None,
        "test_error_code": job.error_code if job else None,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


class ModelPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)
    consent: Literal[True]
    name: str | None = Field(default=None, min_length=1, max_length=100)
    base_url: str | None = Field(default=None, min_length=1, max_length=500)
    model_name: str | None = Field(default=None, min_length=1, max_length=200)
    protocol: Literal["openai_chat", "openai_responses", "anthropic_messages"] | None = None
    timeout_seconds: int | None = Field(default=None, ge=5, le=300)
    token_limit_parameter: Literal["none", "max_tokens", "max_completion_tokens"] | None = None
    product_name_mode: Literal["sku_only", "include_names"] | None = None
    is_default: bool | None = None
    api_key: SecretStr | None = Field(default=None, max_length=4096)
    clear_api_key: bool = False


def ensure_idle(item, db):
    active_report = db.scalar(
        select(Report.id)
        .join(Job, Job.id == Report.job_id)
        .where(Report.model_config_id == item.id, Job.status.in_(["queued", "running"]))
        .limit(1)
    )
    active_question = db.scalar(
        select(ReportMessage.id)
        .join(Report)
        .join(Job, Job.id == ReportMessage.job_id)
        .where(Report.model_config_id == item.id, Job.status.in_(["queued", "running"]))
        .limit(1)
    )
    if active_report or active_question:
        raise AppError(409, "MODEL_BUSY", "报告或追问正在执行，结束后再修改配置。")
    job = db.get(Job, item.test_job_id) if item.test_job_id else None
    if job and job.status in {"queued", "running"}:
        raise AppError(409, "MODEL_BUSY", "连接测试正在执行，结束后再修改或删除。")


CONSENT_VERSION = "2.0"
# v2: follow-up questions, short answer history and merchant notes are sent as data.
CONSENT_FIELDS = ["aggregate_metrics", "quality_summary", "sku", "question_text", "merchant_notes"]


def consent_for(item, url, product_name_mode, actor):
    return {
        "version": CONSENT_VERSION,
        "target_origin": f"{urlsplit(url).scheme}://{urlsplit(url).netloc}",
        "fields": CONSENT_FIELDS
        + (["product_name"] if product_name_mode == "include_names" else []),
        "product_name_mode": product_name_mode,
        "revision": item.revision,
        "confirmed_at": now().isoformat(),
        "confirmed_workspace": str(actor.workspace_id),
    }


def consent_current(item):
    """False for configurations confirmed under the 1.x data scope."""
    consent = item.consent or {}
    return consent.get("version") == CONSENT_VERSION and set(CONSENT_FIELDS) <= set(
        consent.get("fields") or []
    )


def apply(item, payload, db, actor):
    try:
        url = normalize_url(payload.base_url)
    except ProviderError as error:
        raise AppError(422, error.code, MESSAGES[error.code]) from None
    if payload.is_default:
        db.execute(
            update(ModelConfig)
            .where(ModelConfig.workspace_id == actor.workspace_id, ModelConfig.id != item.id)
            .values(is_default=False)
        )
    for field in (
        "name",
        "model_name",
        "protocol",
        "timeout_seconds",
        "token_limit_parameter",
        "product_name_mode",
        "is_default",
    ):
        setattr(item, field, getattr(payload, field))
    item.base_url = url
    item.updated_at = now()
    item.consent = consent_for(item, url, payload.product_name_mode, actor)
    if payload.api_key is not None:
        encrypt(item, payload.api_key.get_secret_value())
    elif payload.clear_api_key:
        item.credential_ciphertext = item.credential_key_version = None
    item.capabilities = item.tested_at = item.test_job_id = None


@router.get("")
def listing(
    request: Request,
    actor: WorkspaceContext = Depends(current_workspace),
    db: Session = Depends(db_session),
):
    items = db.scalars(
        select(ModelConfig)
        .where(ModelConfig.workspace_id == actor.workspace_id)
        .order_by(ModelConfig.created_at.desc())
    ).all()
    return envelope(request, [public(item, db) for item in items])


@router.post("", status_code=201)
def create(
    payload: ModelInput,
    request: Request,
    actor: WorkspaceContext = Depends(mutation_workspace),
    db: Session = Depends(db_session),
):
    lock_configs(db)
    item = ModelConfig(id=uuid.uuid4(), workspace_id=actor.workspace_id, revision=1)
    apply(item, payload, db, actor)
    db.add(item)
    audit(
        db,
        actor,
        "model.created",
        item.id,
        {"revision": item.revision, "credential_set": bool(item.credential_ciphertext)},
    )
    db.commit()
    return envelope(request, public(item, db))


@router.patch("/{config_id}")
def patch(
    config_id: uuid.UUID,
    payload: ModelPatch,
    request: Request,
    actor: WorkspaceContext = Depends(mutation_workspace),
    db: Session = Depends(db_session),
):
    lock_configs(db)
    item = scoped(db, ModelConfig, config_id, actor, lock=True)
    ensure_idle(item, db)
    if payload.revision != item.revision:
        raise AppError(409, "REVISION_CONFLICT", "配置已变化，请刷新后重试。")
    fields = {
        name: getattr(item, name)
        for name in (
            "name",
            "base_url",
            "model_name",
            "protocol",
            "timeout_seconds",
            "token_limit_parameter",
            "product_name_mode",
            "is_default",
        )
    }
    try:
        payload = ModelInput.model_validate({**fields, **payload.model_dump(exclude_unset=True)})
    except ValidationError:
        raise AppError(422, "VALIDATION_ERROR", "请求字段不符合要求，请检查输入。") from None
    item.revision += 1
    apply(item, payload, db, actor)
    audit(
        db,
        actor,
        "model.updated",
        item.id,
        {"revision": item.revision, "credential_set": bool(item.credential_ciphertext)},
    )
    db.commit()
    return envelope(request, public(item, db))


@router.get("/{config_id}")
def detail(
    config_id: uuid.UUID,
    request: Request,
    actor: WorkspaceContext = Depends(current_workspace),
    db: Session = Depends(db_session),
):
    return envelope(request, public(scoped(db, ModelConfig, config_id, actor), db))


@router.delete("/{config_id}", status_code=204)
def remove(
    config_id: uuid.UUID,
    actor: WorkspaceContext = Depends(mutation_workspace),
    db: Session = Depends(db_session),
):
    lock_configs(db)
    item = scoped(db, ModelConfig, config_id, actor, lock=True)
    ensure_idle(item, db)
    if db.scalar(select(Report.id).where(Report.model_config_id == item.id).limit(1)):
        raise AppError(
            409, "MODEL_REFERENCED", "此模型已被历史报告引用，不能删除；可编辑配置或清除密钥。"
        )
    if db.scalar(
        select(ReportSchedule.id).where(ReportSchedule.model_config_id == item.id).limit(1)
    ):
        raise AppError(409, "MODEL_REFERENCED", "此模型已被定时周报使用，请先修改或删除定时任务。")
    audit(db, actor, "model.deleted", item.id)
    db.delete(item)
    db.commit()


@router.post("/{config_id}/consent")
def confirm_consent(
    config_id: uuid.UUID,
    request: Request,
    actor: WorkspaceContext = Depends(mutation_workspace),
    db: Session = Depends(db_session),
):
    """Re-confirm the current data scope without changing the endpoint, key or test results.

    The revision is kept, so reports already using this configuration keep working; each report
    still uses the consent frozen in its own snapshot, and new reports use the confirmed scope.
    """
    lock_configs(db)
    item = scoped(db, ModelConfig, config_id, actor, lock=True)
    ensure_idle(item, db)
    item.consent = consent_for(item, item.base_url, item.product_name_mode, actor)
    item.updated_at = now()
    audit(
        db,
        actor,
        "model.consent_confirmed",
        item.id,
        {"revision": item.revision, "version": CONSENT_VERSION},
    )
    db.commit()
    return envelope(request, public(item, db))


@router.post("/{config_id}/test", status_code=202)
def test(
    config_id: uuid.UUID,
    request: Request,
    actor: WorkspaceContext = Depends(mutation_workspace),
    db: Session = Depends(db_session),
):
    lock_configs(db)
    item = scoped(db, ModelConfig, config_id, actor, lock=True)
    if item.test_job_id:
        existing = db.get(Job, item.test_job_id)
        if existing and existing.status in {"queued", "running"}:
            return envelope(request, {"job_id": str(existing.id)})
    job = schedule(
        db,
        actor.workspace_id,
        "test_model",
        {"config_id": str(item.id), "revision": item.revision},
    )
    item.test_job_id = job.id
    item.capabilities = item.tested_at = None
    db.commit()
    return envelope(request, {"job_id": str(job.id)})
