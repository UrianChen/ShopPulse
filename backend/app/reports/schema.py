from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.metrics.schema import MetricQuery

# Per report/question run. Core deterministic tools are run by the server and not counted.
BUDGETS = {
    "tools": 8,
    "tool_rounds": 5,
    "parallel_tools": 3,
    "requests": 8,
    "repairs": 2,
    "input_bytes": 480000,
    "output_bytes": 64000,
    "input_tokens": 120000,
    "output_tokens": 80000,
    "seconds": 600,
}
PROMPT_VERSION = "2.0"
RULE_VERSION = "1.0"
GRAMMAR_VERSION = "2.0"
LANGUAGES = ("zh", "en")
TOPICS = ("sales", "refund", "cost", "product", "period", "quality", "followup")
VERIFICATION_METRICS = ("net_sales", "gross_profit", "refund_amount_rate", "paid_orders")


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
    language: Literal["zh", "en"] = "zh"


class QuestionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=2000)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Binding(Strict):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,19}$")
    evidence_id: str = Field(min_length=1, max_length=64)
    path: str = Field(min_length=1, max_length=160, pattern=r"^[a-z0-9_.]+$")
    format: Literal["money", "count", "percent", "pp", "entity", "date", "label", "note"]


class Sentence(Strict):
    template: str = Field(min_length=1, max_length=400)
    bindings: list[Binding] = Field(default_factory=list, max_length=4)


class Finding(Strict):
    id: str = Field(pattern=r"^f_[a-z_]{1,30}$")
    topic: Literal["sales", "refund", "cost", "product", "period", "quality", "followup"]
    title: str = Field(min_length=1, max_length=60)
    observation: Sentence
    supporting: list[Sentence] = Field(default_factory=list, max_length=3)
    hypotheses: list[Sentence] = Field(default_factory=list, max_length=3)


class Recommendation(Strict):
    action: Sentence
    rationale_finding_ids: list[str] = Field(min_length=1, max_length=5)
    priority: Literal["high", "medium", "low"]
    effort: Literal["small", "medium", "large"]
    verification_metric: Literal["net_sales", "gross_profit", "refund_amount_rate", "paid_orders"]
    suggested_review_window: Literal["next_week", "next_month"]


class ReportAnalysis(Strict):
    summary: list[Sentence] = Field(min_length=1, max_length=4)
    findings: list[Finding] = Field(min_length=1, max_length=5)
    recommendations: list[Recommendation] = Field(min_length=1, max_length=4)


class SuggestedQuery(Strict):
    start: date
    end_exclusive: date
    comparison: Literal["previous", "none"] = "previous"
    skus: list[str] = Field(default_factory=list, max_length=5)


class AnswerAnalysis(Strict):
    kind: Literal["answer", "clarify", "suggested_query"]
    answer: list[Sentence] = Field(default_factory=list, max_length=4)
    findings: list[Finding] = Field(default_factory=list, max_length=3)
    recommendations: list[Recommendation] = Field(default_factory=list, max_length=3)
    clarify: Sentence | None = None
    options: list[str] = Field(default_factory=list, max_length=3)
    suggested_query: SuggestedQuery | None = None

    @model_validator(mode="after")
    def terminal_state(self):
        if self.kind == "answer" and not self.answer:
            raise ValueError("answer requires sentences")
        if self.kind == "clarify" and self.clarify is None:
            raise ValueError("clarify requires a question")
        if self.kind == "suggested_query" and (
            self.suggested_query is None or self.clarify is None
        ):
            raise ValueError("suggested_query requires a query and a reason")
        return self


# Hand-written schema for providers' strict structured-output modes: every object closes with
# additionalProperties=false, every key is required (nullable where optional) and no
# numeric/string constraints are used. Server-side validation still enforces all limits.
def _nullable(schema):
    return {"anyOf": [schema, {"type": "null"}]}


BINDING_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "evidence_id": {"type": "string"},
        "path": {"type": "string"},
        "format": {
            "type": "string",
            "enum": list(Binding.model_fields["format"].annotation.__args__),
        },
    },
    "required": ["name", "evidence_id", "path", "format"],
    "additionalProperties": False,
}
SENTENCE_SCHEMA = {
    "type": "object",
    "properties": {
        "template": {"type": "string"},
        "bindings": {"type": "array", "items": BINDING_SCHEMA},
    },
    "required": ["template", "bindings"],
    "additionalProperties": False,
}
FINDING_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "topic": {"type": "string", "enum": list(TOPICS)},
        "title": {"type": "string"},
        "observation": SENTENCE_SCHEMA,
        "supporting": {"type": "array", "items": SENTENCE_SCHEMA},
        "hypotheses": {"type": "array", "items": SENTENCE_SCHEMA},
    },
    "required": ["id", "topic", "title", "observation", "supporting", "hypotheses"],
    "additionalProperties": False,
}
RECOMMENDATION_SCHEMA = {
    "type": "object",
    "properties": {
        "action": SENTENCE_SCHEMA,
        "rationale_finding_ids": {"type": "array", "items": {"type": "string"}},
        "priority": {"type": "string", "enum": ["high", "medium", "low"]},
        "effort": {"type": "string", "enum": ["small", "medium", "large"]},
        "verification_metric": {"type": "string", "enum": list(VERIFICATION_METRICS)},
        "suggested_review_window": {"type": "string", "enum": ["next_week", "next_month"]},
    },
    "required": [
        "action",
        "rationale_finding_ids",
        "priority",
        "effort",
        "verification_metric",
        "suggested_review_window",
    ],
    "additionalProperties": False,
}


def output_schema(kind):
    if kind == "report":
        return {
            "type": "object",
            "properties": {
                "summary": {"type": "array", "items": SENTENCE_SCHEMA},
                "findings": {"type": "array", "items": FINDING_SCHEMA},
                "recommendations": {"type": "array", "items": RECOMMENDATION_SCHEMA},
            },
            "required": ["summary", "findings", "recommendations"],
            "additionalProperties": False,
        }
    query = {
        "type": "object",
        "properties": {
            "start": {"type": "string", "format": "date"},
            "end_exclusive": {"type": "string", "format": "date"},
            "comparison": {"type": "string", "enum": ["previous", "none"]},
            "skus": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["start", "end_exclusive", "comparison", "skus"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": ["answer", "clarify", "suggested_query"]},
            "answer": {"type": "array", "items": SENTENCE_SCHEMA},
            "findings": {"type": "array", "items": FINDING_SCHEMA},
            "recommendations": {"type": "array", "items": RECOMMENDATION_SCHEMA},
            "clarify": _nullable(SENTENCE_SCHEMA),
            "options": {"type": "array", "items": {"type": "string"}},
            "suggested_query": _nullable(query),
        },
        "required": [
            "kind",
            "answer",
            "findings",
            "recommendations",
            "clarify",
            "options",
            "suggested_query",
        ],
        "additionalProperties": False,
    }
