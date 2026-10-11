import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime

import psutil
from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import session as db_module
from app.db.models import (
    CostRow,
    CostVersion,
    DatasetVersion,
    ImportDraft,
    Job,
    OrderLine,
    Upload,
    ValidationIssue,
    now,
)
from app.ingestion.storage import object_path, read_json, write_json
from app.jobs.queue import owned


def schedule(db, workspace_id, job_type, payload):
    job = Job(
        workspace_id=workspace_id,
        type=job_type,
        payload=payload,
        request_hash=hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
        idempotency_key=f"{job_type}:{uuid.uuid4()}",
    )
    db.add(job)
    db.flush()
    return job


def isolated(request, workspace_id, module="app.ingestion.runner", memory_mib=768, job=None):
    prefix = f"{workspace_id}/staging/{uuid.uuid4().hex}"
    request_key, output_key = prefix + ".input.json", prefix + ".output.json"
    write_json(request_key, request)
    try:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                module,
                str(object_path(request_key)),
                str(object_path(output_key)),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={**os.environ, "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"},
        )
        deadline = time.monotonic() + settings().parse_timeout_seconds
        monitor = psutil.Process(process.pid)
        next_check = 0
        try:
            while process.poll() is None:
                if job is not None and time.monotonic() >= next_check:
                    next_check = time.monotonic() + 1
                    with Session(db_module.engine()) as db:
                        if not db.scalar(select(Job.id).where(*owned(job))):
                            return {"error": "任务已取消或租约失效。"}
                if time.monotonic() > deadline:
                    return {"error": "解析超时，已终止隔离进程，请拆分文件后重试。"}
                try:
                    processes = [monitor, *monitor.children(recursive=True)]
                    rss = 0
                    for child in processes:
                        try:
                            rss += child.memory_info().rss
                        except psutil.NoSuchProcess:
                            continue
                    if rss > memory_mib * 1024 * 1024:
                        return {"error": f"计算内存超过 {memory_mib} MiB 限制，请缩小范围后重试。"}
                except psutil.NoSuchProcess:
                    break
                try:
                    process.wait(timeout=0.1)
                except subprocess.TimeoutExpired:
                    pass
        finally:
            # PDF renderers spawn Chromium children; reap the whole process tree on timeout.
            try:
                children = monitor.children(recursive=True)
            except psutil.NoSuchProcess:
                children = []
            for child in children:
                try:
                    child.kill()
                except psutil.NoSuchProcess:
                    pass
            if process.poll() is None:
                process.kill()
            process.wait()
            psutil.wait_procs(children, timeout=3)
        if process.returncode or not object_path(output_key).exists():
            return {"error": "解析进程失败或达到资源限制，请拆分文件后重试。"}
        return read_json(output_key)
    finally:
        object_path(request_key).unlink(missing_ok=True)
        object_path(output_key).unlink(missing_ok=True)


def execute(job: Job):
    with Session(db_module.engine()) as db:
        if job.type == "parse_upload":
            upload = db.get(Upload, uuid.UUID(job.payload["upload_id"]))
            request = {
                "action": "parse",
                "path": str(object_path(upload.storage_key)),
                "kind": upload.kind,
                "config": {},
                "max_rows": settings().max_import_rows,
            }
        else:
            draft = db.get(ImportDraft, uuid.UUID(job.payload["import_id"]))
            if draft.revision != job.payload["revision"]:
                return commit_result(job, {"superseded": True})
            if job.type == "publish_dataset":
                result = read_json(draft.staging_key)
                return commit_result(job, result)
            upload = db.get(Upload, draft.upload_id)
            costs = []
            if draft.config.get("cost_version_id"):
                for c in db.scalars(
                    select(CostRow).where(
                        CostRow.version_id == uuid.UUID(draft.config["cost_version_id"])
                    )
                ):
                    costs.append(
                        {
                            "sku": c.sku,
                            "unit_cost": str(c.unit_cost),
                            "currency": c.currency,
                            "effective_from": c.effective_from.isoformat(),
                            "effective_to": c.effective_to.isoformat() if c.effective_to else None,
                        }
                    )
            request = {
                "action": "validate",
                "path": str(object_path(upload.storage_key)),
                "kind": draft.kind,
                "config": draft.config,
                "resolutions": draft.resolutions,
                "sha256": upload.sha256,
                "max_rows": settings().max_import_rows,
                "costs": costs,
            }
    result = isolated(request, job.workspace_id, job=job)
    return commit_result(job, result)


def commit_result(job, result):
    with Session(db_module.engine()) as db, db.begin():
        current_job = db.scalar(select(Job).where(*owned(job)).with_for_update())
        if not current_job:
            return False
        if job.type == "parse_upload":
            upload = db.get(Upload, uuid.UUID(job.payload["upload_id"]))
            upload.status = "failed" if result.get("error") else "ready"
            upload.metadata_json = result.get("metadata")
            upload.error_message = result.get("error")
        else:
            draft = db.scalar(
                select(ImportDraft)
                .where(ImportDraft.id == uuid.UUID(job.payload["import_id"]))
                .with_for_update()
            )
            expected_status = "validating" if job.type == "validate_import" else "publishing"
            if (
                draft.revision != job.payload["revision"]
                or draft.status != expected_status
                or result.get("superseded")
            ):
                result = {"superseded": True}
            elif result.get("error"):
                draft.status = "failed"
                draft.error_message = result["error"]
            elif job.type == "validate_import":
                from sqlalchemy import delete

                db.execute(delete(ValidationIssue).where(ValidationIssue.import_id == draft.id))
                for offset in range(0, len(result["issues"]), 1000):
                    db.execute(
                        insert(ValidationIssue),
                        [
                            {**issue, "import_id": draft.id, "revision": draft.revision}
                            for issue in result["issues"][offset : offset + 1000]
                        ],
                    )
                key = (
                    f"{job.workspace_id}/staging/{draft.id}-{draft.revision}-{job.lease_token}.json"
                )
                write_json(key, result)
                draft.staging_key = key
                draft.validated_revision = draft.revision
                draft.summary = result["summary"]
                draft.error_message = None
                draft.status = (
                    "review_required"
                    if result["summary"]["errors"] or result["summary"]["unacknowledged"]
                    else "ready"
                )
                result = {
                    "import_id": str(draft.id),
                    "summary": draft.summary,
                    "revision": draft.revision,
                }
            elif job.type == "publish_dataset":
                if (
                    draft.validated_revision != draft.revision
                    or draft.summary["errors"]
                    or draft.summary["unacknowledged"]
                ):
                    raise ValueError("Unvalidated revision cannot be published")
                result = publish(db, draft, result["rows"])
        current_job.status = "failed" if result.get("error") else "succeeded"
        current_job.error_code = "IMPORT_FAILED" if result.get("error") else None
        current_job.result = result
        current_job.lease_expires_at = None
        current_job.updated_at = now()
        return True


def publish(db, draft, rows):
    upload = db.get(Upload, draft.upload_id)
    snapshot = {
        "file_sha256": upload.sha256,
        "config": draft.config,
        "resolutions": draft.resolutions,
        "engine_version": "1.0",
        "metric_definition_version": "1.0",
        "workspace_revision": draft.workspace_revision,
    }
    fingerprint = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
    # Serialize identical publications across different imports; a concurrent winner is reused.
    from sqlalchemy import text

    lock = int(hashlib.sha256(f"{draft.workspace_id}:{fingerprint}".encode()).hexdigest()[:15], 16)
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock})
    model = CostVersion if draft.kind == "costs" else DatasetVersion
    existing = db.scalar(
        select(model).where(
            model.workspace_id == draft.workspace_id, model.fingerprint == fingerprint
        )
    )
    if existing:
        version = existing
    else:
        snapshot.update(
            {
                "source_file_id": str(upload.id),
                "import_revision": draft.revision,
                "confirmed_at": now().isoformat(),
            }
        )
        kwargs = {
            "workspace_id": draft.workspace_id,
            "import_id": draft.id,
            "name": draft.name,
            "fingerprint": fingerprint,
            "snapshot": snapshot,
            "row_count": len(rows),
        }
        if draft.kind == "orders":
            kwargs.update(
                cost_version_id=uuid.UUID(draft.config["cost_version_id"])
                if draft.config.get("cost_version_id")
                else None,
                summary=draft.summary,
            )
        version = model(**kwargs)
        db.add(version)
        db.flush()
        for offset in range(0, len(rows), 1000):
            batch = []
            for row in rows[offset : offset + 1000]:
                data = dict(row)
                if draft.kind == "costs":
                    data.pop("source_row_number")
                    data.update(
                        version_id=version.id,
                        effective_from=datetime.fromisoformat(data["effective_from"]),
                        effective_to=datetime.fromisoformat(data["effective_to"])
                        if data["effective_to"]
                        else None,
                    )
                else:
                    data.update(
                        dataset_id=version.id,
                        source_file_id=upload.id,
                        paid_at=datetime.fromisoformat(data["paid_at"]),
                    )
                batch.append(data)
            db.execute(insert(CostRow if draft.kind == "costs" else OrderLine), batch)
    draft.status = "published"
    draft.published_id = version.id
    return {"version_id": str(version.id), "kind": draft.kind, "reused": bool(existing)}
