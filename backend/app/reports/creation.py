"""Shared report creation for the API and the scheduler."""

import hashlib
import uuid

from sqlalchemy import func, select, text

from app.core.errors import AppError
from app.db.models import Job, Report
from app.reports.tools import digest

FROZEN_MODEL_FIELDS = (
    "name",
    "base_url",
    "model_name",
    "protocol",
    "revision",
    "timeout_seconds",
    "token_limit_parameter",
    "product_name_mode",
    "capabilities",
    "consent",
)


def idempotency(db, workspace_id, route, key, payload):
    token = "report:" + hashlib.sha256(f"{route}:{key}".encode()).hexdigest()
    lock = int(hashlib.sha256(f"{workspace_id}:{token}".encode()).hexdigest()[:15], 16)
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock})
    job = db.scalar(
        select(Job).where(Job.workspace_id == workspace_id, Job.idempotency_key == token)
    )
    hashed = digest(payload)
    if job and job.request_hash != hashed:
        raise AppError(409, "IDEMPOTENCY_CONFLICT", "相同幂等键不能用于不同请求。")
    if job and job.error_code == "RESOURCE_DELETED":
        raise AppError(410, "RESOURCE_DELETED", "此请求关联的数据已删除，请创建新请求。")
    return job, token, hashed


def build_report(
    db, workspace_id, payload, dataset, cached, model, parent, token, hashed, schedule_id=None
):
    """Create the report row and its job. Callers hold the config lock and commit."""
    frozen = {field: getattr(model, field) for field in FROZEN_MODEL_FIELDS} if model else None
    report_id, series_id, revision = uuid.uuid4(), uuid.uuid4(), 1
    if parent is not None:
        series_id = parent.series_id
        # Shared config lock serializes all revisions, including branches from different parents.
        revision = (
            db.scalar(select(func.max(Report.revision)).where(Report.series_id == series_id)) + 1
        )
    job = Job(
        workspace_id=workspace_id,
        type="build_report",
        payload={"report_id": str(report_id)},
        request_hash=hashed,
        idempotency_key=token,
    )
    db.add(job)
    db.flush()
    report = Report(
        id=report_id,
        workspace_id=workspace_id,
        dataset_id=dataset.id,
        metric_snapshot_id=cached.id,
        model_config_id=model.id if model else None,
        model_snapshot=frozen,
        series_id=series_id,
        parent_id=parent.id if parent is not None else None,
        revision=revision,
        title=payload.title,
        query=cached.query,
        rules=payload.rules.model_dump(),
        language=payload.language,
        schedule_id=schedule_id,
        job_id=job.id,
    )
    db.add(report)
    return report
