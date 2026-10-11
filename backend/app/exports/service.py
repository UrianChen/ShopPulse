import hashlib
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import session as db_module
from app.db.models import ExportArtifact, Job, Report, ToolResult, now
from app.ingestion.service import isolated
from app.ingestion.storage import object_path
from app.jobs.queue import owned


def execute(job):
    key = f"{job.workspace_id}/exports/{job.id}-{job.lease_token}.bin"
    target = object_path(key)
    target.parent.mkdir(parents=True, exist_ok=True)
    with Session(db_module.engine()) as db:
        artifact = db.get(ExportArtifact, uuid.UUID(job.payload["export_id"]))
        report = db.get(Report, artifact.report_id)
        ids = [uuid.UUID(e["evidence_id"]) for e in report.content["evidence_index"]]
        evidence = [e.payload for e in db.scalars(select(ToolResult).where(ToolResult.id.in_(ids)))]
        request = {
            "format": artifact.format,
            "content": report.content,
            "evidence": evidence,
            "target": str(target),
        }
    try:
        result = isolated(request, job.workspace_id, "app.exports.runner", memory_mib=1536, job=job)
        with Session(db_module.engine()) as db, db.begin():
            current = db.scalar(select(Job).where(*owned(job)).with_for_update())
            if not current:
                return
            artifact = db.get(ExportArtifact, uuid.UUID(job.payload["export_id"]))
            artifact.status = "failed" if result.get("error") or not target.exists() else "ready"
            artifact.error_code = "EXPORT_RENDER_FAILED" if artifact.status == "failed" else None
            if artifact.status == "ready":
                artifact.storage_key = key
                artifact.size_bytes = target.stat().st_size
                artifact.sha256 = hashlib.sha256(target.read_bytes()).hexdigest()
            current.status = "succeeded" if artifact.status == "ready" else "failed"
            current.error_code = artifact.error_code
            current.result = {"export_id": str(artifact.id)}
            current.lease_expires_at, current.updated_at = None, now()
            if artifact.status == "ready":
                key = None  # The committed artifact now owns this file.
    finally:
        if key:
            target.unlink(missing_ok=True)
