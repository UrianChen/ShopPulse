"""Response models for the JSON API.

They document what the endpoints already return and must never reshape it: every field the
endpoints put into a response is declared here, in the same order, and free-form JSON (report
content, evidence payloads, frozen snapshots, capabilities) stays ``dict[str, Any]``. Timestamps
serialize with ``isoformat()`` exactly like FastAPI's ``jsonable_encoder`` did before, and the
routers render with ``JSONResponse`` (``json.dumps``) rather than Pydantic's JSON fast path, so
number and string formatting is unchanged too. The test suite compares every response with the
encoder's output (``tests/response_guard.py``).
"""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, PlainSerializer, WithJsonSchema

Timestamp = Annotated[
    datetime,
    PlainSerializer(lambda value: value.isoformat(), return_type=str),
    WithJsonSchema({"type": "string", "format": "date-time"}),
]
Json = dict[str, Any]
Kind = Literal["orders", "costs"]


class Meta(BaseModel):
    request_id: str


class Envelope[T](BaseModel):
    data: T
    meta: Meta


class Page[T](BaseModel):
    total: int
    items: list[T]


class Workspace(BaseModel):
    id: str
    name: str
    timezone: str
    currency: str


class Job(BaseModel):
    id: str
    type: str
    status: str
    attempt: int
    result: Json | None
    error_code: str | None
    created_at: Timestamp
    updated_at: Timestamp


class JobAccepted(BaseModel):
    job_id: str


class UploadAccepted(BaseModel):
    upload_id: str
    job_id: str


class Upload(BaseModel):
    id: str
    name: str
    kind: Kind
    status: str
    sha256: str
    size_bytes: int
    metadata: Json | None
    source_available: bool
    source_deleted_at: Timestamp | None
    error_message: str | None


class ImportDraft(BaseModel):
    id: str
    upload_id: str
    name: str
    kind: Kind
    revision: int
    config: Json
    resolutions: Json
    status: str
    validated_revision: int | None
    summary: Json | None
    published_id: str | None
    error_message: str | None
    created_at: Timestamp


class ValidationIssue(BaseModel):
    code: str
    severity: str
    row_number: int
    field: str
    message: str
    acknowledged: bool


class DatasetVersion(BaseModel):
    """A published order or cost version; ``snapshot`` is the frozen import configuration."""

    id: str
    name: str
    row_count: int
    created_at: Timestamp
    snapshot: Json
    summary: Json | None


class SourceFile(DatasetVersion):
    upload_id: str
    source_available: bool
    source_deleted_at: Timestamp | None


class OrderPreviewRow(BaseModel):
    source_row_number: int
    order_id: str
    sku: str | None
    quantity: int
    line_paid_minor: int
    line_refund_minor: int | None
    unit_cost: str | None


class CostPreviewRow(BaseModel):
    sku: str
    unit_cost: str
    currency: str
    effective_from: str
    effective_to: str | None


class DatasetDetail(SourceFile):
    preview: list[OrderPreviewRow]


class CostVersionDetail(SourceFile):
    preview: list[CostPreviewRow]


class MetricSnapshot(BaseModel):
    id: str
    job_id: str
    status: str
    error_code: str | None
    result: Json | None
    created_at: Timestamp


class ModelConfig(BaseModel):
    id: str
    name: str
    base_url: str
    model_name: str
    review_model_name: str | None
    protocol: Literal["openai_chat", "openai_responses", "anthropic_messages"]
    revision: int
    is_default: bool
    timeout_seconds: int
    token_limit_parameter: Literal["none", "max_tokens", "max_completion_tokens"]
    product_name_mode: Literal["sku_only", "include_names"]
    consent: Json | None
    consent_current: bool
    has_api_key: bool
    capabilities: Json | None
    tested_at: Timestamp | None
    test_job_id: str | None
    test_status: str | None
    test_error_code: str | None
    created_at: Timestamp
    updated_at: Timestamp


class Report(BaseModel):
    id: str
    title: str
    status: str
    revision: int
    series_id: str
    parent_id: str | None
    dataset_id: str
    query: Json
    rules: Json
    model_config_id: str | None
    job_id: str
    job_status: str
    error_code: str | None
    generation_mode: str | None
    language: str
    schedule_id: str | None
    created_at: Timestamp


class ReportDetail(Report):
    content: Json | None


class AgentRun(BaseModel):
    id: str
    job_id: str
    attempt: int
    status: str
    steps: list[Json]
    usage: Json
    budgets: Json
    error_code: str | None
    trace_id: str | None
    debug_entries: int
    created_at: Timestamp
    completed_at: Timestamp | None


class ActionItem(BaseModel):
    id: str
    report_id: str
    position: int
    text: str
    verification_metric: str
    review_window: str
    priority: str
    effort: str
    status: str
    note: str | None
    evaluation: Json | None
    revision: int
    created_at: Timestamp
    updated_at: Timestamp


class WorkspaceAction(ActionItem):
    report_title: str | None


class MessageAccepted(BaseModel):
    message_id: str
    job_id: str


class ReportMessage(BaseModel):
    id: str
    sequence: int
    question: str
    status: str
    answer: Json | None
    created_at: Timestamp


class ExportArtifact(BaseModel):
    id: uuid.UUID
    report_id: uuid.UUID
    job_id: uuid.UUID
    format: str
    status: str
    sha256: str | None
    size_bytes: int | None
    error_code: str | None
    expires_at: Timestamp
    created_at: Timestamp


class Period(BaseModel):
    start: str
    end_exclusive: str


class Schedule(BaseModel):
    id: str
    name: str
    title: str
    dataset_id: str | None
    model_config_id: str | None
    period_days: int
    weekday: int
    hour: int
    timezone: str
    enabled: bool
    rules: Json
    language: str
    has_webhook: bool
    webhook_format: str
    series_id: str | None
    last_report_id: str | None
    last_run_at: Timestamp | None
    next_run_at: Timestamp | None
    last_status: str | None
    next_period: Period | None
    revision: int
    created_at: Timestamp
    updated_at: Timestamp


class ScheduleRun(BaseModel):
    status: str
    report_id: str | None


class Note(BaseModel):
    id: str
    start_date: str
    end_exclusive: str
    kind: str
    text: str
    created_at: Timestamp
    updated_at: Timestamp


class WorkspaceSettings(BaseModel):
    revision: int
    name: str
    timezone: str
    currency: str
    raw_retention_days: int
    export_retention_days: int


class Disk(BaseModel):
    total_bytes: int
    free_bytes: int


class Worker(BaseModel):
    id: str
    heartbeat_at: Timestamp
    online: bool
    job_id: uuid.UUID | None
    rss_bytes: int


class ServiceStatus(BaseModel):
    jobs: dict[str, int]
    oldest_queued_seconds: int
    failures: dict[str, int]
    disk: Disk
    api_rss_bytes: int
    workers: list[Worker]


class AuditEntry(BaseModel):
    id: uuid.UUID
    action: str
    target_id: str
    details: Json
    created_at: Timestamp


class DeletionPlan(BaseModel):
    kind: str
    target: str
    workspace_id: str
    ids: dict[str, list[str]]
    counts: dict[str, int]
    token: str


class CleanupPlan(BaseModel):
    sources: list[str]
    exports: list[str]
    orphans: list[str]
    revision: int
    token: str
    counts: dict[str, int]


class DeletionResult(BaseModel):
    deleted: dict[str, int]
    pending_files: int


class CleanupResult(BaseModel):
    cleaned: dict[str, int]
    pending_files: int
