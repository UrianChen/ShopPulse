from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.metrics.schema import MetricQuery

BUDGETS = {"tools": 8, "requests": 4, "input_bytes": 12000, "output_bytes": 8000, "seconds": 180}
PROMPT_VERSION = "1.1"
RULE_VERSION = "1.0"


class Rules(BaseModel):
    model_config = ConfigDict(extra="forbid")
    min_orders: int = Field(default=20, ge=20, le=1000, strict=True)
    sales_change: float = Field(default=0.2, ge=0.01, le=10)
    refund_rate: float = Field(default=0.1, ge=0.01, le=1)
    margin_drop_pp: float = Field(default=5, ge=0.1, le=100)
    concentration: float = Field(default=0.7, ge=0.1, le=1)
    mad_z: float = Field(default=3.5, ge=1, le=10)


class ReportInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(default="经营周报", min_length=1, max_length=150)
    query: MetricQuery
    model_config_id: UUID | None = None
    parent_id: UUID | None = None
    rules: Rules = Field(default_factory=Rules)


class QuestionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=2000)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Binding(Strict):
    evidence_id: str
    path: str
    format: Literal["money", "count", "percent"]


class Sentence(Strict):
    text_template: str = Field(max_length=300)
    bindings: dict[str, Binding]


class Finding(Strict):
    id: str = Field(pattern=r"^f_[a-z_]{1,30}$")
    title: str = Field(min_length=1, max_length=80)
    observation: Sentence
    evidence_refs: list[str] = Field(min_length=1, max_length=8)
    hypotheses: list[str] = Field(default_factory=list, max_length=3)
    limitations: list[str] = Field(default_factory=list, max_length=3)


class Recommendation(Strict):
    action: str = Field(min_length=1, max_length=250)
    rationale_finding_ids: list[str] = Field(min_length=1, max_length=5)
    priority: Literal["high", "medium", "low"]
    effort: Literal["small", "medium", "large"]
    verification_metric: Literal["net_sales", "gross_profit", "refund_amount_rate", "paid_orders"]
    suggested_review_window: Literal["next_week", "next_month"]


class Analysis(Strict):
    summary: list[Sentence] = Field(min_length=1, max_length=4)
    findings: list[Finding] = Field(min_length=1, max_length=4)
    recommendations: list[Recommendation] = Field(min_length=1, max_length=4)
