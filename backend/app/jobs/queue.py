import uuid
from datetime import timedelta

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import ImportDraft, Job, Upload, now
from app.db.session import engine


def claim() -> Job | None:
    current = now()
    with Session(engine(), expire_on_commit=False) as db, db.begin():
        expired = and_(Job.status == "running", Job.lease_expires_at < current)
        exhausted = db.scalars(
            update(Job)
            .where(expired, Job.attempt >= settings().job_max_attempts)
            .values(status="failed", error_code="LEASE_RETRIES_EXHAUSTED", updated_at=current)
            .returning(Job)
        ).all()
        for failed in exhausted:
            from app.ops.jobs import settle

            settle(db, failed, "LEASE_RETRIES_EXHAUSTED")
            if failed.type in {"build_report", "report_question"}:
                from app.reports.service import fail

                fail(db, failed, "LEASE_RETRIES_EXHAUSTED")
            message = "处理进程多次中断，任务已终止，请重新上传或保存配置后重试。"
            if failed.type == "parse_upload":
                db.execute(
                    update(Upload)
                    .where(
                        Upload.id == uuid.UUID(failed.payload["upload_id"]),
                        Upload.status == "parsing",
                    )
                    .values(status="failed", error_message=message)
                )
            elif failed.type in {"validate_import", "publish_dataset"}:
                db.execute(
                    update(ImportDraft)
                    .where(
                        ImportDraft.id == uuid.UUID(failed.payload["import_id"]),
                        ImportDraft.revision == failed.payload["revision"],
                        ImportDraft.status
                        == ("validating" if failed.type == "validate_import" else "publishing"),
                    )
                    .values(status="failed", error_message=message)
                )
        job = db.scalar(
            select(Job)
            .where(
                or_(and_(Job.status == "queued", Job.available_at <= current), expired),
                Job.attempt < settings().job_max_attempts,
            )
            .order_by(Job.available_at, Job.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if job:
            job.status = "running"
            job.attempt += 1
            job.lease_token += 1
            job.lease_expires_at = current + timedelta(seconds=settings().job_lease_seconds)
            job.updated_at = current
        return job


def owned(job: Job):
    return (
        Job.id == job.id,
        Job.status == "running",
        Job.lease_token == job.lease_token,
        Job.lease_expires_at > now(),
    )


def heartbeat(job: Job) -> bool:
    with Session(engine()) as db, db.begin():
        result = db.execute(
            update(Job)
            .where(*owned(job))
            .values(
                lease_expires_at=now() + timedelta(seconds=settings().job_lease_seconds),
                updated_at=now(),
            )
        )
        return result.rowcount == 1


def finish(job: Job, result: dict | None = None, error_code: str | None = None) -> bool:
    with Session(engine()) as db, db.begin():
        updated = db.execute(
            update(Job)
            .where(*owned(job))
            .values(
                status="failed" if error_code else "succeeded",
                result=result,
                error_code=error_code,
                lease_expires_at=None,
                updated_at=now(),
            )
        )
        return updated.rowcount == 1
