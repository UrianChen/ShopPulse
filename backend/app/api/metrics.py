import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import WorkspaceContext, current_workspace, envelope, mutation_workspace
from app.api.imports import scoped
from app.core.errors import AppError
from app.db.models import DatasetVersion, Job, MetricProduct, MetricSnapshot, OrderLine
from app.db.session import db_session
from app.metrics.schema import MetricQuery
from app.metrics.service import request_snapshot

router = APIRouter(prefix="/api/v1")


def public_snapshot(db, value):
    job = db.get(Job, value.job_id)
    return {
        "id": str(value.id),
        "job_id": str(value.job_id),
        "status": "succeeded" if value.result is not None else job.status,
        "error_code": job.error_code,
        "result": value.result,
        "created_at": value.created_at,
    }


@router.post("/metrics/query")
def query_metrics(
    payload: MetricQuery,
    request: Request,
    actor: WorkspaceContext = Depends(mutation_workspace),
    db: Session = Depends(db_session),
):
    dataset = scoped(db, DatasetVersion, payload.dataset_id, actor)
    cached = request_snapshot(db, dataset, payload)
    return envelope(request, public_snapshot(db, cached))


@router.get("/metrics/{snapshot_id}")
def get_metrics(
    snapshot_id: uuid.UUID,
    request: Request,
    actor: WorkspaceContext = Depends(current_workspace),
    db: Session = Depends(db_session),
):
    cached = scoped(db, MetricSnapshot, snapshot_id, actor)
    return envelope(request, public_snapshot(db, cached))


@router.get("/metrics/{snapshot_id}/products")
def products(
    snapshot_id: uuid.UUID,
    request: Request,
    sort: Literal["net_sales", "gross_profit", "refund_amount", "paid_units"] = "net_sales",
    direction: Literal["asc", "desc"] = "desc",
    offset: int = 0,
    limit: int = 20,
    focus: Literal["all", "negative_profit", "refunded"] = "all",
    actor: WorkspaceContext = Depends(current_workspace),
    db: Session = Depends(db_session),
):
    cached = scoped(db, MetricSnapshot, snapshot_id, actor)
    if cached.result is None:
        raise AppError(409, "METRICS_NOT_READY", "指标尚未完成，请等待计算或重试。")
    if offset < 0 or not 1 <= limit <= 100:
        raise AppError(422, "INVALID_PAGE", "分页参数无效。")
    stmt = select(MetricProduct).where(MetricProduct.snapshot_id == cached.id)
    if focus == "negative_profit":
        stmt = stmt.where(MetricProduct.gross_profit < 0)
    elif focus == "refunded":
        stmt = stmt.where(MetricProduct.refund_amount > 0)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    column = getattr(MetricProduct, sort)
    order = column.desc() if direction == "desc" else column.asc()
    values = db.scalars(
        stmt.order_by(order.nulls_last(), MetricProduct.group_key).offset(offset).limit(limit)
    )
    return envelope(request, {"total": total, "items": [r.payload for r in values]})


@router.get("/datasets/{dataset_id}/skus")
def sku_choices(
    dataset_id: uuid.UUID,
    request: Request,
    search: str = "",
    actor: WorkspaceContext = Depends(current_workspace),
    db: Session = Depends(db_session),
):
    dataset = scoped(db, DatasetVersion, dataset_id, actor)
    if len(search) > 128:
        raise AppError(422, "INVALID_SEARCH", "SKU 搜索最多 128 字符。")
    stmt = select(OrderLine.sku).where(
        OrderLine.dataset_id == dataset.id, OrderLine.sku.is_not(None)
    )
    if search:
        stmt = stmt.where(OrderLine.sku.contains(search, autoescape=True))
    return envelope(request, list(db.scalars(stmt.distinct().order_by(OrderLine.sku).limit(100))))
