"""Webhook delivery when a scheduled report is ready. URLs are sealed; bodies are never stored."""

import uuid
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import session as db_module
from app.db.models import Job, Report, ReportSchedule, now
from app.jobs.queue import owned
from app.providers.credentials import unseal
from app.providers.egress import ProviderError, post_webhook

FORMATS = ("generic", "slack", "feishu", "wecom", "dingtalk")


def message_text(report):
    content = report.content or {}
    end = date.fromisoformat(report.query["end_exclusive"]) - timedelta(days=1)
    lines = [report.title, f"{report.query['start']} – {end.isoformat()}"]
    lines += [s["text"] for s in content.get("summary") or []][:4]
    lines.append(f"{settings().origin}/reports/{report.id}")
    return "\n".join(lines)


def body_for(fmt, report):
    text = message_text(report)
    if fmt == "slack":
        return {"text": text}
    if fmt == "feishu":
        return {"msg_type": "text", "content": {"text": text}}
    if fmt in {"wecom", "dingtalk"}:
        return {"msgtype": "text", "text": {"content": text}}
    content = report.content or {}
    return {
        "event": "report.ready",
        "report_id": str(report.id),
        "title": report.title,
        "status": report.status,
        "period": {"start": report.query["start"], "end_exclusive": report.query["end_exclusive"]},
        "summary": [s["text"] for s in content.get("summary") or []][:4],
        "generation_mode": content.get("generation_mode"),
        "url": f"{settings().origin}/reports/{report.id}",
    }


def execute(job):
    with Session(db_module.engine()) as db:
        report = db.scalar(
            select(Report).where(
                Report.id == uuid.UUID(job.payload["report_id"]),
                Report.workspace_id == job.workspace_id,
            )
        )
        schedule = db.get(ReportSchedule, uuid.UUID(job.payload["schedule_id"]))
        target, body, fmt = None, None, "generic"
        if report and schedule and schedule.workspace_id == job.workspace_id:
            if schedule.webhook_ciphertext:
                target = (
                    "webhook",
                    schedule.workspace_id,
                    schedule.id,
                    schedule.webhook_ciphertext,
                    schedule.webhook_key_version,
                )
                fmt = schedule.webhook_format
                body = body_for(fmt, report)
    code, status = None, None
    if target is None:
        code = "WEBHOOK_UNAVAILABLE"
    else:
        try:
            status = post_webhook(unseal(*target), body)
        except ProviderError as error:
            code = error.code
        except Exception:
            code = "CREDENTIAL_UNAVAILABLE"
        finally:
            target = None
    with Session(db_module.engine()) as db, db.begin():
        current = db.scalar(select(Job).where(*owned(job)).with_for_update())
        if not current:
            return
        schedule = db.get(
            ReportSchedule, uuid.UUID(job.payload["schedule_id"]), with_for_update=True
        )
        if schedule is not None:
            schedule.last_status = "NOTIFIED" if code is None else ("NOTIFY_FAILED:" + code)[:40]
            schedule.updated_at = now()
        current.status = "succeeded" if code is None else "failed"
        current.error_code = code
        current.result = {"http_status": status, "format": fmt}
        current.lease_expires_at, current.updated_at = None, now()
