"""Scheduled weekly reports. The worker calls ``tick`` between jobs; no extra service needed."""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import session as db_module
from app.db.models import (
    DatasetVersion,
    ModelConfig,
    Report,
    ReportSchedule,
    Workspace,
    now,
)
from app.metrics.service import request_snapshot
from app.providers.credentials import lock_configs
from app.reports import creation
from app.reports.schema import ReportInput

logger = logging.getLogger("shoppulse")


def next_run(weekday, hour, timezone, after=None):
    """Next local ``weekday`` at ``hour``:00 strictly after ``after``, returned in UTC."""
    local = (after or now()).astimezone(ZoneInfo(timezone))
    candidate = local.replace(hour=hour, minute=0, second=0, microsecond=0) + timedelta(
        days=(weekday - local.weekday()) % 7
    )
    if candidate <= local:
        candidate += timedelta(days=7)
    return candidate.astimezone(UTC)


def coverage_end(dataset):
    value = dataset.snapshot["config"]["options"]["coverage_end_exclusive"]
    return datetime.fromisoformat(value).date()


def latest_dataset(db, workspace_id):
    return db.scalar(
        select(DatasetVersion)
        .where(DatasetVersion.workspace_id == workspace_id)
        .order_by(DatasetVersion.created_at.desc(), DatasetVersion.id)
        .limit(1)
    )


def run_schedule(schedule_id, force=False):
    """Create the next report for a schedule. Returns {"status", "report_id"}."""
    with Session(db_module.engine(), expire_on_commit=False) as db:
        schedule = db.scalar(
            select(ReportSchedule)
            .where(ReportSchedule.id == schedule_id)
            .with_for_update(skip_locked=True)
        )
        if schedule is None:
            return {"status": "BUSY", "report_id": None}
        if not force and (
            not schedule.enabled or schedule.next_run_at is None or schedule.next_run_at > now()
        ):
            db.rollback()
            return {"status": "NOT_DUE", "report_id": None}
        workspace = db.get(Workspace, schedule.workspace_id)

        def finish(status, report_id=None):
            row = db.get(ReportSchedule, schedule_id, with_for_update=True)
            row.last_status, row.last_run_at, row.updated_at = status, now(), now()
            if report_id is not None and status == "CREATED":
                row.last_report_id = report_id
            if not force or row.next_run_at is None or row.next_run_at <= now():
                row.next_run_at = next_run(row.weekday, row.hour, workspace.timezone)
            db.commit()
            return {"status": status, "report_id": str(report_id) if report_id else None}

        dataset = (
            db.get(DatasetVersion, schedule.dataset_id)
            if schedule.dataset_id
            else latest_dataset(db, schedule.workspace_id)
        )
        if dataset is None:
            return finish("NO_DATASET")
        end = coverage_end(dataset)
        start = end - timedelta(days=schedule.period_days)
        last = db.get(Report, schedule.last_report_id) if schedule.last_report_id else None
        if (
            not force
            and last is not None
            and last.dataset_id == dataset.id
            and last.query["end_exclusive"] == end.isoformat()
        ):
            return finish("NO_NEW_DATA", last.id)
        last_day = (end - timedelta(days=1)).isoformat()
        payload = ReportInput.model_validate(
            {
                "title": f"{schedule.title} · {start.isoformat()} – {last_day}"[:150],
                "query": {
                    "dataset_id": str(dataset.id),
                    "start": start.isoformat(),
                    "end_exclusive": end.isoformat(),
                    "comparison": "previous",
                },
                "model_config_id": str(schedule.model_config_id)
                if schedule.model_config_id
                else None,
                "parent_id": str(last.id) if last is not None else None,
                "rules": schedule.rules,
                "language": schedule.language,
            }
        )
        key = f"{schedule.id}:{dataset.id}:{end.isoformat()}" + (
            f":manual:{uuid.uuid4()}" if force else ""
        )
        data = payload.model_dump(mode="json")
        workspace_id, timezone = schedule.workspace_id, workspace.timezone
        db.commit()  # Release the row lock before the metrics dependency commits its own work.
        cached = request_snapshot(db, dataset, payload.query)
        lock_configs(db)
        existing, token, hashed = creation.idempotency(db, workspace_id, "schedule", key, data)
        if existing:
            db.rollback()
            return finish("ALREADY_CREATED", uuid.UUID(existing.payload["report_id"]))
        model = db.get(ModelConfig, schedule.model_config_id) if schedule.model_config_id else None
        parent = db.get(Report, last.id, with_for_update=True) if last is not None else None
        report = creation.build_report(
            db, workspace_id, payload, dataset, cached, model, parent, token, hashed, schedule.id
        )
        row = db.get(ReportSchedule, schedule_id, with_for_update=True)
        row.series_id = report.series_id
        row.last_report_id = report.id
        row.last_status, row.last_run_at, row.updated_at = "CREATED", now(), now()
        if not force or row.next_run_at is None or row.next_run_at <= now():
            row.next_run_at = next_run(row.weekday, row.hour, timezone)
        db.commit()
        return {"status": "CREATED", "report_id": str(report.id)}


def tick(limit=5):
    if not settings().scheduler_enabled:
        return []
    with Session(db_module.engine()) as db:
        due = list(
            db.scalars(
                select(ReportSchedule.id)
                .where(ReportSchedule.enabled.is_(True), ReportSchedule.next_run_at <= now())
                .order_by(ReportSchedule.next_run_at)
                .limit(limit)
            )
        )
    results = []
    for schedule_id in due:
        try:
            results.append(run_schedule(schedule_id))
        except Exception:
            logger.error("schedule_failed", extra={"event": "schedule_failed"})
            with Session(db_module.engine()) as db, db.begin():
                row = db.get(ReportSchedule, schedule_id, with_for_update=True)
                workspace = db.get(Workspace, row.workspace_id)
                row.last_status, row.updated_at = "FAILED", now()
                row.next_run_at = next_run(row.weekday, row.hour, workspace.timezone)
    return results


def period_preview(dataset, period_days):
    end = coverage_end(dataset)
    return {
        "start": (end - timedelta(days=period_days)).isoformat(),
        "end_exclusive": end.isoformat(),
    }


__all__ = ["next_run", "period_preview", "run_schedule", "tick"]
