import os
import uuid

import psutil
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import AppError
from app.db import session as db_module
from app.db.models import (
    ExportArtifact,
    ImportDraft,
    MetricSnapshot,
    ModelConfig,
    Report,
    ReportMessage,
    Upload,
    WorkerPulse,
    now,
)
from app.reports.service import fail

WORKER_ID = uuid.uuid4().hex


def pulse(job_id=None):
    with Session(db_module.engine()) as db, db.begin():
        values = {
            "id": WORKER_ID,
            "heartbeat_at": now(),
            "job_id": job_id,
            "rss_bytes": psutil.Process(os.getpid()).memory_info().rss,
        }
        db.execute(
            insert(WorkerPulse)
            .values(**values)
            .on_conflict_do_update(index_elements=[WorkerPulse.id], set_=values)
        )


def settle(db, job, code):
    if job.type in {"build_report", "report_question"}:
        fail(db, job, code)
    elif job.type == "export_report":
        row = db.get(ExportArtifact, uuid.UUID(job.payload["export_id"]))
        if row:
            row.status, row.error_code = ("cancelled" if code == "CANCELLED" else "failed"), code
    elif job.type == "parse_upload":
        row = db.get(Upload, uuid.UUID(job.payload["upload_id"]))
        if row:
            row.status, row.error_message = "failed", "任务已终止，可重试或重新上传。"
    elif job.type in {"validate_import", "publish_dataset"}:
        row = db.get(ImportDraft, uuid.UUID(job.payload["import_id"]))
        if row and row.revision == job.payload["revision"]:
            row.status, row.error_message = "failed", "任务已终止，可重试或修改导入配置。"


def cancel(db, job):
    if job.status not in {"queued", "running"}:
        return
    job.status, job.error_code = "cancelled", "CANCELLED"
    job.lease_token += 1
    job.lease_expires_at, job.updated_at = None, now()
    settle(db, job, "CANCELLED")


def retry(db, job):
    if job.status not in {"failed", "cancelled"} or job.attempt >= settings().job_max_attempts:
        raise AppError(
            409, "RETRY_REJECTED", "当前任务不可重试或已达重试上限，请重新创建业务任务。"
        )
    row = None
    if job.type in {"validate_import", "publish_dataset"}:
        row = db.get(ImportDraft, uuid.UUID(job.payload["import_id"]), with_for_update=True)
        if not row or row.revision != job.payload["revision"] or row.status != "failed":
            raise AppError(409, "REVISION_CONFLICT", "导入已变化，请使用当前配置重新提交。")
        row.status = "validating" if job.type == "validate_import" else "publishing"
    elif job.type == "parse_upload":
        row = db.get(Upload, uuid.UUID(job.payload["upload_id"]))
        if not row or row.source_deleted_at:
            raise AppError(410, "SOURCE_EXPIRED", "原文件已清理，请重新上传。")
        row.status = "parsing"
    elif job.type == "build_metrics":
        row = db.get(MetricSnapshot, uuid.UUID(job.payload["snapshot_id"]))
        if not row or row.job_id != job.id or row.result:
            raise AppError(409, "SUPERSEDED", "已有新的指标任务。")
    elif job.type == "test_model":
        row = db.get(ModelConfig, uuid.UUID(job.payload["config_id"]))
        if not row or row.test_job_id != job.id or row.revision != job.payload["revision"]:
            raise AppError(409, "REVISION_CONFLICT", "模型配置或测试任务已变化。")
    elif job.type == "build_report":
        row = db.get(Report, uuid.UUID(job.payload["report_id"]))
        if not row:
            raise AppError(410, "DELETED", "报告已删除。")
        row.status = "queued"
    elif job.type == "report_question":
        row = db.get(ReportMessage, uuid.UUID(job.payload["message_id"]))
        if not row or db.scalar(
            select(ReportMessage.id).where(
                ReportMessage.report_id == row.report_id,
                ReportMessage.status.in_(["queued", "running"]),
            )
        ):
            raise AppError(409, "QUESTION_BUSY", "追问已删除或有其他追问正在执行。")
        row.status = "queued"
    elif job.type == "export_report":
        row = db.get(ExportArtifact, uuid.UUID(job.payload["export_id"]))
        if not row or row.expires_at <= now():
            raise AppError(410, "EXPORT_EXPIRED", "导出已过期或删除，请重新生成。")
        row.status, row.error_code = "queued", None
    job.status, job.error_code, job.result = "queued", None, None
    job.available_at, job.updated_at = now(), now()
    job.lease_token += 1
    job.lease_expires_at = None
