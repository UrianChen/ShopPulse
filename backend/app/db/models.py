import uuid
from datetime import UTC, date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now():
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Workspace(Base):
    __tablename__ = "workspaces"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(50), unique=True, default="default")
    name: Mapped[str] = mapped_column(String(100), default="我的店铺")
    timezone: Mapped[str] = mapped_column(String(60), default="Asia/Shanghai")
    currency: Mapped[str] = mapped_column(String(3), default="CNY")
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    raw_retention_days: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    export_retention_days: Mapped[int] = mapped_column(Integer, default=30, server_default="30")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Upload(Base):
    __tablename__ = "uploads"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), index=True)
    storage_key: Mapped[str] = mapped_column(String(255), unique=True)
    original_name: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(30), default="uploaded")
    kind: Mapped[str] = mapped_column(String(20), default="orders", server_default="orders")
    metadata_json: Mapped[dict | None] = mapped_column(JSON)
    error_message: Mapped[str | None] = mapped_column(String(250))
    source_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("workspace_id", "idempotency_key", name="uq_job_idempotency"),
        Index("ix_jobs_claim", "status", "available_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), index=True)
    type: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON)
    request_hash: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(30), default="queued")
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    lease_token: Mapped[int] = mapped_column(Integer, default=0)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    result: Mapped[dict | None] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ImportDraft(Base):
    __tablename__ = "imports"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), index=True)
    upload_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("uploads.id"))
    kind: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(120))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    workspace_revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    resolutions: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(30), default="mapping_required")
    validated_revision: Mapped[int | None] = mapped_column(Integer)
    summary: Mapped[dict | None] = mapped_column(JSON)
    staging_key: Mapped[str | None] = mapped_column(String(255))
    published_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    error_message: Mapped[str | None] = mapped_column(String(250))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ValidationIssue(Base):
    __tablename__ = "validation_issues"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    import_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("imports.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    code: Mapped[str] = mapped_column(String(60))
    severity: Mapped[str] = mapped_column(String(12))
    row_number: Mapped[int] = mapped_column(Integer)
    field: Mapped[str] = mapped_column(String(60))
    message: Mapped[str] = mapped_column(String(250))
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)


class CostVersion(Base):
    __tablename__ = "cost_versions"
    __table_args__ = (UniqueConstraint("workspace_id", "fingerprint"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), index=True)
    import_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("imports.id"))
    name: Mapped[str] = mapped_column(String(120))
    fingerprint: Mapped[str] = mapped_column(String(64))
    snapshot: Mapped[dict] = mapped_column(JSON)
    row_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class CostRow(Base):
    __tablename__ = "cost_rows"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cost_versions.id"), index=True)
    sku: Mapped[str] = mapped_column(String(128))
    unit_cost: Mapped[object] = mapped_column(Numeric(20, 6))
    currency: Mapped[str] = mapped_column(String(3))
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DatasetVersion(Base):
    __tablename__ = "dataset_versions"
    __table_args__ = (UniqueConstraint("workspace_id", "fingerprint"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), index=True)
    import_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("imports.id"))
    cost_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cost_versions.id"))
    name: Mapped[str] = mapped_column(String(120))
    fingerprint: Mapped[str] = mapped_column(String(64))
    snapshot: Mapped[dict] = mapped_column(JSON)
    summary: Mapped[dict] = mapped_column(JSON)
    row_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OrderLine(Base):
    __tablename__ = "order_lines"
    __table_args__ = (
        UniqueConstraint("dataset_id", "line_id"),
        Index("ix_lines_period", "dataset_id", "paid_at"),
        Index("ix_lines_sku", "dataset_id", "sku"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    dataset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dataset_versions.id"), index=True)
    line_id: Mapped[str] = mapped_column(String(64))
    order_id: Mapped[str] = mapped_column(String(128))
    order_line_id: Mapped[str | None] = mapped_column(String(128))
    sku: Mapped[str | None] = mapped_column(String(128))
    product_name: Mapped[str] = mapped_column(String(4096))
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    quantity: Mapped[int] = mapped_column(Integer)
    line_paid_minor: Mapped[int] = mapped_column(BigInteger)
    line_refund_minor: Mapped[int | None] = mapped_column(BigInteger)
    restocked_quantity: Mapped[int | None] = mapped_column(Integer)
    unit_cost: Mapped[object | None] = mapped_column(Numeric(20, 6))
    currency: Mapped[str] = mapped_column(String(3))
    source_row_number: Mapped[int] = mapped_column(Integer)
    source_file_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("uploads.id"))
    quality: Mapped[dict] = mapped_column(JSON)


class MetricSnapshot(Base):
    __tablename__ = "metric_snapshots"
    __table_args__ = (UniqueConstraint("workspace_id", "cache_key"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), index=True)
    dataset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dataset_versions.id"), index=True)
    cache_key: Mapped[str] = mapped_column(String(64))
    engine_version: Mapped[str] = mapped_column(String(30))
    query: Mapped[dict] = mapped_column(JSON)
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id"))
    result: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class MetricProduct(Base):
    __tablename__ = "metric_products"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "group_key"),
        Index("ix_metric_product_sales", "snapshot_id", "net_sales"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("metric_snapshots.id"), index=True)
    group_key: Mapped[str] = mapped_column(String(140))
    sku: Mapped[str | None] = mapped_column(String(128))
    product_name: Mapped[str] = mapped_column(String(4096))
    net_sales: Mapped[object | None] = mapped_column(Numeric(40, 0))
    gross_profit: Mapped[object | None] = mapped_column(Numeric(40, 0))
    refund_amount: Mapped[object | None] = mapped_column(Numeric(40, 0))
    paid_units: Mapped[int] = mapped_column(BigInteger)
    payload: Mapped[dict] = mapped_column(JSON)


class ModelConfig(Base):
    __tablename__ = "model_configs"
    __table_args__ = (
        Index("uq_model_default", "workspace_id", unique=True, postgresql_where=text("is_default")),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    base_url: Mapped[str] = mapped_column(String(500))
    model_name: Mapped[str] = mapped_column(String(200))
    protocol: Mapped[str] = mapped_column(
        String(30), default="openai_chat", server_default="openai_chat"
    )
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=45)
    token_limit_parameter: Mapped[str] = mapped_column(String(30), default="none")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    product_name_mode: Mapped[str] = mapped_column(String(30), default="sku_only")
    consent: Mapped[dict] = mapped_column(JSON)
    credential_ciphertext: Mapped[str | None] = mapped_column(Text)
    credential_key_version: Mapped[int | None] = mapped_column(Integer)
    capabilities: Mapped[dict | None] = mapped_column(JSON)
    tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    test_job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (UniqueConstraint("series_id", "revision"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), index=True)
    dataset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dataset_versions.id"))
    metric_snapshot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("metric_snapshots.id"))
    model_config_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("model_configs.id"))
    model_snapshot: Mapped[dict | None] = mapped_column(JSON)
    series_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("reports.id"))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    title: Mapped[str] = mapped_column(String(150))
    query: Mapped[dict] = mapped_column(JSON)
    rules: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30), default="queued")
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id"))
    content: Mapped[dict | None] = mapped_column(JSON)
    language: Mapped[str] = mapped_column(String(5), default="zh", server_default="zh")
    schedule_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("report_schedules.id"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (UniqueConstraint("job_id", "attempt"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    report_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reports.id"), index=True)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id"))
    attempt: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="computing")
    prompt_version: Mapped[str] = mapped_column(String(30), default="1.0")
    budgets: Mapped[dict] = mapped_column(JSON)
    steps: Mapped[list] = mapped_column(JSON, default=list)
    usage: Mapped[dict] = mapped_column(JSON, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(64))
    trace_id: Mapped[str | None] = mapped_column(String(32))
    debug: Mapped[list | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ToolResult(Base):
    __tablename__ = "tool_results"
    __table_args__ = (Index("ix_tool_results_cache", "report_id", "tool", "args_hash"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    report_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reports.id"), index=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    tool: Mapped[str] = mapped_column(String(50))
    args_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ReportMessage(Base):
    __tablename__ = "report_messages"
    __table_args__ = (UniqueConstraint("report_id", "sequence"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    report_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reports.id"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    question: Mapped[str] = mapped_column(String(2000))
    status: Mapped[str] = mapped_column(String(30), default="queued")
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id"))
    answer: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ExportArtifact(Base):
    __tablename__ = "exports"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), index=True)
    report_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reports.id"), index=True)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id"))
    format: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(30), default="queued")
    storage_key: Mapped[str | None] = mapped_column(String(255))
    sha256: Mapped[str | None] = mapped_column(String(64))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    error_code: Mapped[str | None] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), index=True)
    action: Mapped[str] = mapped_column(String(60))
    target_id: Mapped[str] = mapped_column(String(100))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class WorkerPulse(Base):
    __tablename__ = "worker_pulses"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    rss_bytes: Mapped[int] = mapped_column(BigInteger, default=0)


class ActionItem(Base):
    """A recommendation the merchant can track; evaluated against later reports."""

    __tablename__ = "action_items"
    __table_args__ = (UniqueConstraint("report_id", "position"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), index=True)
    report_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reports.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(String(500))
    verification_metric: Mapped[str] = mapped_column(String(40))
    review_window: Mapped[str] = mapped_column(String(20))
    priority: Mapped[str] = mapped_column(String(10))
    effort: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20), default="open")
    note: Mapped[str | None] = mapped_column(String(500))
    evaluation: Mapped[dict | None] = mapped_column(JSON)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class MerchantNote(Base):
    """Merchant-authored context (promotions, holidays...) that analysis may cite as data."""

    __tablename__ = "merchant_notes"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), index=True)
    start_date: Mapped[date] = mapped_column(Date)
    end_exclusive: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(20))
    text: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ReportSchedule(Base):
    __tablename__ = "report_schedules"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(150))
    dataset_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("dataset_versions.id"))
    model_config_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("model_configs.id"))
    period_days: Mapped[int] = mapped_column(Integer, default=7)
    weekday: Mapped[int] = mapped_column(Integer, default=0)
    hour: Mapped[int] = mapped_column(Integer, default=8)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    rules: Mapped[dict] = mapped_column(JSON)
    language: Mapped[str] = mapped_column(String(5), default="zh")
    webhook_ciphertext: Mapped[str | None] = mapped_column(Text)
    webhook_key_version: Mapped[int | None] = mapped_column(Integer)
    webhook_format: Mapped[str] = mapped_column(String(20), default="generic")
    series_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    last_report_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_status: Mapped[str | None] = mapped_column(String(40))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
