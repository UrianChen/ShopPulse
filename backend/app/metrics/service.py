import hashlib
import json
import uuid

from sqlalchemy import insert, select, text
from sqlalchemy.orm import Session

from app.db import session as db_module
from app.db.models import DatasetVersion, Job, MetricProduct, MetricSnapshot, OrderLine, now
from app.ingestion.normalize import timestamp
from app.ingestion.service import isolated, schedule
from app.jobs.queue import owned
from app.metrics.schema import DEFINITION_VERSION, ENGINE_VERSION, MetricQuery


def request_snapshot(db, dataset, query):
    payload = query.model_dump(mode="json")
    key = hashlib.sha256(
        json.dumps(
            {
                "query": payload,
                "dataset_fingerprint": dataset.fingerprint,
                "cost_version_id": str(dataset.cost_version_id),
                "snapshot": dataset.snapshot,
                "engine": ENGINE_VERSION,
                "definitions": DEFINITION_VERSION,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    lock = int(
        hashlib.sha256(f"metrics:{dataset.workspace_id}:{key}".encode()).hexdigest()[:15], 16
    )
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock})
    cached = db.scalar(
        select(MetricSnapshot)
        .where(MetricSnapshot.workspace_id == dataset.workspace_id, MetricSnapshot.cache_key == key)
        .with_for_update()
    )
    if cached and (
        cached.result is not None or db.get(Job, cached.job_id).status in {"queued", "running"}
    ):
        db.commit()
        return cached
    if not cached:
        cached = MetricSnapshot(
            workspace_id=dataset.workspace_id,
            dataset_id=dataset.id,
            cache_key=key,
            query=payload,
            engine_version=ENGINE_VERSION,
        )
        db.add(cached)
        db.flush()
    job = schedule(db, dataset.workspace_id, "build_metrics", {"snapshot_id": str(cached.id)})
    cached.job_id = job.id
    db.commit()
    return cached


def load_rows(db, dataset, query, limit=None):
    """Calculator inputs only; avoid ORM identity-map overhead for 100,000 rows."""
    options = dataset.snapshot["config"]["options"]
    start = min(query.start, query.compare_start or query.start)
    end = max(query.end_exclusive, query.compare_end_exclusive or query.end_exclusive)
    statement = select(
        OrderLine.order_id,
        OrderLine.sku,
        OrderLine.product_name,
        OrderLine.paid_at,
        OrderLine.quantity,
        OrderLine.line_paid_minor,
        OrderLine.line_refund_minor,
        OrderLine.restocked_quantity,
        OrderLine.unit_cost,
        OrderLine.quality,
    ).where(
        OrderLine.dataset_id == dataset.id,
        OrderLine.paid_at >= timestamp(start.isoformat(), options["timezone"]),
        OrderLine.paid_at < timestamp(end.isoformat(), options["timezone"]),
    )
    if query.skus:
        statement = statement.where(OrderLine.sku.in_(query.skus))
    statement = statement.order_by(OrderLine.source_row_number)
    if limit is not None:
        statement = statement.limit(limit + 1)
    return [
        {
            "order_id": r.order_id,
            "sku": r.sku,
            "product_name": r.product_name,
            "paid_at": r.paid_at.isoformat(),
            "quantity": r.quantity,
            "line_paid_minor": r.line_paid_minor,
            "line_refund_minor": r.line_refund_minor,
            "restocked_quantity": r.restocked_quantity,
            "unit_cost": str(r.unit_cost) if r.unit_cost is not None else None,
            "quality": r.quality,
        }
        for r in db.execute(statement.execution_options(yield_per=2000))
    ]


def execute(job):
    with Session(db_module.engine()) as db:
        cached = db.get(MetricSnapshot, uuid.UUID(job.payload["snapshot_id"]))
        dataset = db.get(DatasetVersion, cached.dataset_id)
        query = MetricQuery.model_validate(cached.query)
        rows = load_rows(db, dataset, query)
        request = {"rows": rows, "snapshot": dataset.snapshot, "query": cached.query}
    result = isolated(
        request, job.workspace_id, module="app.metrics.runner", memory_mib=1536, job=job
    )
    if result.get("error"):
        from app.jobs.queue import finish

        return finish(job, error_code="METRICS_FAILED")
    return commit_result(job, result)


def commit_result(job, output):
    with Session(db_module.engine()) as db, db.begin():
        current = db.scalar(select(Job).where(*owned(job)).with_for_update())
        if not current:
            return False
        cached = db.scalar(
            select(MetricSnapshot)
            .where(MetricSnapshot.id == uuid.UUID(job.payload["snapshot_id"]))
            .with_for_update()
        )
        if cached.job_id != job.id:
            return False
        if cached.result is None:
            cached.result = output["result"]
            for offset in range(0, len(output["products"]), 500):
                batch = []
                for p in output["products"][offset : offset + 500]:
                    m = p["current"]["metrics"]
                    batch.append(
                        {
                            "snapshot_id": cached.id,
                            "group_key": p["group_key"],
                            "sku": p["sku"],
                            "product_name": p["product_name"],
                            "net_sales": m["net_sales"]["value"],
                            "gross_profit": m["gross_profit"]["value"],
                            "refund_amount": m["refund_amount"]["value"],
                            "paid_units": int(m["paid_units"]["value"] or 0),
                            "payload": p,
                        }
                    )
                db.execute(insert(MetricProduct), batch)
        current.status = "succeeded"
        current.result = {"snapshot_id": str(cached.id)}
        current.lease_expires_at = None
        current.updated_at = now()
        return True
