import uuid
from datetime import timedelta

from sqlalchemy import delete, select, text, update

from app.api.imports import scoped
from app.core.errors import AppError
from app.db.models import (
    AgentRun,
    CostRow,
    CostVersion,
    DatasetVersion,
    ExportArtifact,
    ImportDraft,
    Job,
    MetricProduct,
    MetricSnapshot,
    OrderLine,
    Report,
    ReportMessage,
    ToolResult,
    Upload,
    ValidationIssue,
    Workspace,
    now,
)
from app.ingestion.storage import object_path, storage_root
from app.reports.tools import digest


def idle_lock(db, workspace_id):
    # Block concurrent job submission/claim during the impact check and destructive transaction.
    db.execute(text("LOCK TABLE jobs IN SHARE ROW EXCLUSIVE MODE"))
    if db.scalar(
        select(Job.id)
        .where(Job.workspace_id == workspace_id, Job.status.in_(["queued", "running"]))
        .limit(1)
    ):
        raise AppError(409, "WORKSPACE_BUSY", "请等待全部任务完成或取消后再执行清理/删除。")


def deletion_plan(db, actor, kind, target):
    model = {"report": Report, "dataset": DatasetVersion, "cost": CostVersion, "upload": Upload}[
        kind
    ]
    scoped(db, model, target, actor)
    workspace = actor.workspace_id
    uploads, costs, datasets, reports, drafts = set(), set(), set(), set(), set()
    if kind == "upload":
        uploads.add(target)
        drafts.update(db.scalars(select(ImportDraft.id).where(ImportDraft.upload_id == target)))
        costs.update(db.scalars(select(CostVersion.id).where(CostVersion.import_id.in_(drafts))))
        datasets.update(
            db.scalars(select(DatasetVersion.id).where(DatasetVersion.import_id.in_(drafts)))
        )
    if kind == "cost":
        costs.add(target)
    if kind == "dataset":
        datasets.add(target)
    if kind == "report":
        reports.add(target)
    datasets.update(
        db.scalars(select(DatasetVersion.id).where(DatasetVersion.cost_version_id.in_(costs)))
    )
    reports.update(db.scalars(select(Report.id).where(Report.dataset_id.in_(datasets))))
    snapshots = set(
        db.scalars(select(MetricSnapshot.id).where(MetricSnapshot.dataset_id.in_(datasets)))
    )
    exports = set(
        db.scalars(select(ExportArtifact.id).where(ExportArtifact.report_id.in_(reports)))
    )
    rows = {
        "uploads": uploads,
        "costs": costs,
        "datasets": datasets,
        "reports": reports,
        "imports": drafts,
        "snapshots": snapshots,
        "exports": exports,
    }
    plan = {k: sorted(str(v) for v in values) for k, values in rows.items()}
    return {
        "kind": kind,
        "target": str(target),
        "workspace_id": str(workspace),
        "ids": plan,
        "counts": {k: len(v) for k, v in plan.items()},
        "token": digest(plan),
    }


def remove(db, plan):
    ids = {k: [uuid.UUID(v) for v in values] for k, values in plan["ids"].items()}
    files = [
        r.storage_key
        for r in db.scalars(select(ExportArtifact).where(ExportArtifact.id.in_(ids["exports"])))
        if r.storage_key
    ]
    files += [
        r.storage_key for r in db.scalars(select(Upload).where(Upload.id.in_(ids["uploads"])))
    ]
    files += [
        r.staging_key
        for r in db.scalars(select(ImportDraft).where(ImportDraft.id.in_(ids["imports"])))
        if r.staging_key
    ]
    db.execute(delete(ExportArtifact).where(ExportArtifact.id.in_(ids["exports"])))
    db.execute(delete(ToolResult).where(ToolResult.report_id.in_(ids["reports"])))
    db.execute(delete(AgentRun).where(AgentRun.report_id.in_(ids["reports"])))
    db.execute(delete(ReportMessage).where(ReportMessage.report_id.in_(ids["reports"])))
    db.execute(update(Report).where(Report.parent_id.in_(ids["reports"])).values(parent_id=None))
    db.execute(delete(Report).where(Report.id.in_(ids["reports"])))
    db.execute(delete(MetricProduct).where(MetricProduct.snapshot_id.in_(ids["snapshots"])))
    db.execute(delete(MetricSnapshot).where(MetricSnapshot.id.in_(ids["snapshots"])))
    db.execute(delete(OrderLine).where(OrderLine.dataset_id.in_(ids["datasets"])))
    db.execute(delete(DatasetVersion).where(DatasetVersion.id.in_(ids["datasets"])))
    db.execute(delete(CostRow).where(CostRow.version_id.in_(ids["costs"])))
    db.execute(delete(CostVersion).where(CostVersion.id.in_(ids["costs"])))
    # Remaining unpublished drafts cannot keep a removed cost version as their selected input.
    for draft in db.scalars(
        select(ImportDraft).where(ImportDraft.workspace_id == uuid.UUID(plan["workspace_id"]))
    ):
        if draft.published_id in ids["datasets"] + ids["costs"]:
            draft.status, draft.published_id = "deleted", None
        if (
            draft.config.get("cost_version_id") in plan["ids"]["costs"]
            and draft.status != "published"
        ):
            draft.config = {**draft.config, "cost_version_id": None}
            draft.revision += 1
            draft.status = "mapping_required"
    db.execute(delete(ValidationIssue).where(ValidationIssue.import_id.in_(ids["imports"])))
    db.execute(delete(ImportDraft).where(ImportDraft.id.in_(ids["imports"])))
    db.execute(delete(Upload).where(Upload.id.in_(ids["uploads"])))
    all_ids = {v for values in plan["ids"].values() for v in values}
    for job in db.scalars(select(Job).where(Job.workspace_id == uuid.UUID(plan["workspace_id"]))):
        if any(str(v) in all_ids for v in job.payload.values()):
            job.result, job.status, job.error_code = None, "cancelled", "RESOURCE_DELETED"
    return files


def cleanup_plan(db, workspace_id):
    workspace = db.get(Workspace, workspace_id)
    sources = []
    if workspace.raw_retention_days:
        for upload in db.scalars(
            select(Upload).where(
                Upload.workspace_id == workspace_id,
                Upload.source_deleted_at.is_(None),
                Upload.created_at < now() - timedelta(days=workspace.raw_retention_days),
            )
        ):
            drafts = list(db.scalars(select(ImportDraft).where(ImportDraft.upload_id == upload.id)))
            if drafts and all(d.status in {"published", "deleted"} for d in drafts):
                sources.append(upload)
    exports = list(
        db.scalars(
            select(ExportArtifact).where(
                ExportArtifact.workspace_id == workspace_id,
                ExportArtifact.expires_at < now(),
                ExportArtifact.status.notin_(["expired", "queued"]),
            )
        )
    )
    referenced = {
        r.storage_key for r in db.scalars(select(Upload).where(Upload.source_deleted_at.is_(None)))
    }
    referenced.update(
        r.storage_key
        for r in db.scalars(select(ExportArtifact).where(ExportArtifact.status == "ready"))
    )
    referenced.update(
        r.staging_key
        for r in db.scalars(
            select(ImportDraft).where(ImportDraft.status.notin_(["published", "deleted"]))
        )
    )
    orphans = []
    base = storage_root() / str(workspace_id)
    if base.exists():
        for file in base.rglob("*"):
            if file.is_file() and not file.is_symlink():
                key = file.relative_to(storage_root()).as_posix()
                if (
                    key not in referenced
                    and file.stat().st_mtime < (now() - timedelta(days=1)).timestamp()
                ):
                    orphans.append(key)
    data = {
        "sources": sorted(str(r.id) for r in sources),
        "exports": sorted(str(r.id) for r in exports),
        "orphans": sorted(orphans),
        "revision": workspace.revision,
    }
    return {
        **data,
        "token": digest(data),
        "counts": {k: len(data[k]) for k in ("sources", "exports", "orphans")},
    }


def clean(db, plan):
    files = list(plan["orphans"])
    for id in plan["sources"]:
        row = db.get(Upload, uuid.UUID(id))
        row.source_deleted_at = now()
        row.metadata_json = None
        files.append(row.storage_key)
    for id in plan["exports"]:
        row = db.get(ExportArtifact, uuid.UUID(id))
        if row.storage_key:
            files.append(row.storage_key)
        row.status, row.storage_key = "expired", None
    return files


def unlink_files(files, workspace_id):
    failed = 0
    for key in set(files):
        if not key.startswith(str(workspace_id) + "/"):
            raise ValueError("Storage scope mismatch")
        try:
            object_path(key).unlink(missing_ok=True)
        except OSError:
            failed += 1
    return failed
