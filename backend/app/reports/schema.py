from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.metrics.schema import MetricQuery

# Per report/question run. Core deterministic tools are run by the server and not counted.
# Hypothesis tests run in the server too; ``tests`` caps them per run, ``hypotheses`` per wave.
BUDGETS = {
    "tools": 8,
    "tool_rounds": 5,
    "parallel_tools": 3,
    "requests": 8,
    "repairs": 2,
    "hypotheses": 5,
    "waves": 2,
    "tests": 10,
    "input_bytes": 480000,
    "output_bytes": 64000,
    "input_tokens": 120000,
    "output_tokens": 80000,
    "seconds": 600,
}
# Follow-up questions answer within an existing report and reuse its tested hypotheses.
QUESTION_BUDGETS = {
    **BUDGETS,
    "tools": 4,
    "tool_rounds": 2,
    "requests": 5,
    "repairs": 1,
    "waves": 0,
    "tests": 0,
}


def budgets_for(kind):
    return QUESTION_BUDGETS if kind == "question" else BUDGETS


PROMPT_VERSION = "3.1"
RULE_VERSION = "1.0"
GRAMMAR_VERSION = "3.0"
TOOL_VERSION = "3.0"
# A SKU-level comparison whose larger period has fewer paid orders than this is a small sample.
SKU_MIN_ORDERS = 10
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


class Operand(Strict):
    evidence_id: str = Field(min_length=1, max_length=64)
    path: str = Field(min_length=1, max_length=160, pattern=r"^[a-z0-9_.]+$")


class Derive(Strict):
    """Computed binding: the binding's own value (a) combined with ``b``."""

    op: Literal["diff", "ratio", "multiple", "share"]
    b: Operand


FORMAT = Literal["money", "count", "percent", "pp", "multiple", "entity", "date", "label", "note"]


class Binding(Strict):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,19}$")
    evidence_id: str = Field(min_length=1, max_length=64)
    path: str = Field(min_length=1, max_length=160, pattern=r"^[a-z0-9_.]+$")
    format: FORMAT
    derive: Derive | None = None


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
    hypothesis_ids: list[str] = Field(default_factory=list, max_length=3)


class RuledOut(Strict):
    hypothesis_id: str = Field(min_length=1, max_length=40)
    sentence: Sentence


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
    ruled_out: list[RuledOut] = Field(default_factory=list, max_length=4)


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


# ----------------------------------------------------------------- hypotheses (v3)
HYPOTHESIS_OPS = ("gt", "lt", "abs_ge", "abs_gt", "share_ge", "rank_le", "same_sign")
SELECT_LISTS = ("items", "gainers", "decliners", "checks", "points", "windows", "trend")
SELECT_KEYS = ("sku", "start", "code", "date")
DECIMAL = r"^-?\d{1,12}(\.\d{1,12})?$"


class Select(Strict):
    """Pick a list element by key instead of position (positions change between runs)."""

    list: Literal["items", "gainers", "decliners", "checks", "points", "windows", "trend"]
    key: Literal["sku", "start", "code", "date"]
    value: str = Field(min_length=1, max_length=128)


class PredicateOperand(Strict):
    source: str = Field(min_length=1, max_length=64)  # "test" or an evidence id you were given
    path: str = Field(default="", max_length=160, pattern=r"^[a-z0-9_.]*$")
    select: Select | None = None


class Expect(Strict):
    op: Literal["gt", "lt", "abs_ge", "abs_gt", "share_ge", "rank_le", "same_sign"]
    a: PredicateOperand
    b: PredicateOperand | None = None
    threshold: str | None = Field(default=None, pattern=DECIMAL)
    k: int | None = Field(default=None, ge=1, le=50)


class ToolArguments(Strict):
    """Union of tool arguments; null fields are dropped before the tool's own validation."""

    metric: str | None = None
    direction: str | None = None
    top_k: int | None = None
    start: str | None = None
    end_exclusive: str | None = None
    metrics: list[str] | None = None
    sku: str | None = None
    by: str | None = None


class CheckSpec(Strict):
    tool: str = Field(min_length=1, max_length=64)
    arguments: ToolArguments = Field(default_factory=ToolArguments)


class HypothesisSpec(Strict):
    id: str = Field(pattern=r"^h_[a-z0-9_]{1,30}$")
    statement: Sentence
    test: CheckSpec
    expect: Expect


class Plan(Strict):
    hypotheses: list[HypothesisSpec] = Field(default_factory=list, max_length=5)


class Patch(Strict):
    at: str = Field(min_length=1, max_length=120)
    sentence: Sentence | None = None
    text: str | None = Field(default=None, max_length=300)
    ids: list[str] | None = Field(default=None, max_length=5)


class PatchReply(Strict):
    patches: list[Patch] = Field(min_length=1, max_length=12)


REVIEW_CODES = (
    "DIRECTION_MISMATCH",
    "NO_VERIFICATION",
    "WEAK_NOTE_LINK",
    "OVERCLAIM",
    "UNSUPPORTED_CLAIM",
)


class ReviewIssue(Strict):
    at: str = Field(min_length=1, max_length=120)
    code: Literal[
        "DIRECTION_MISMATCH", "NO_VERIFICATION", "WEAK_NOTE_LINK", "OVERCLAIM", "UNSUPPORTED_CLAIM"
    ]
    note: str = Field(default="", max_length=200)


class Review(Strict):
    issues: list[ReviewIssue] = Field(default_factory=list, max_length=8)


# Hand-written schema for providers' strict structured-output modes: every object closes with
# additionalProperties=false, every key is required (nullable where optional) and no
# numeric/string constraints are used. Server-side validation still enforces all limits.
def _nullable(schema):
    return {"anyOf": [schema, {"type": "null"}]}


def _object(properties):
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


OPERAND_SCHEMA = _object({"evidence_id": {"type": "string"}, "path": {"type": "string"}})
BINDING_SCHEMA = _object(
    {
        "name": {"type": "string"},
        "evidence_id": {"type": "string"},
        "path": {"type": "string"},
        "format": {"type": "string", "enum": list(FORMAT.__args__)},
        "derive": _nullable(
            _object(
                {
                    "op": {"type": "string", "enum": ["diff", "ratio", "multiple", "share"]},
                    "b": OPERAND_SCHEMA,
                }
            )
        ),
    }
)
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
        "hypothesis_ids": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "id",
        "topic",
        "title",
        "observation",
        "supporting",
        "hypotheses",
        "hypothesis_ids",
    ],
    "additionalProperties": False,
}
RULED_OUT_SCHEMA = _object({"hypothesis_id": {"type": "string"}, "sentence": SENTENCE_SCHEMA})
_STRING = {"type": "string"}
PREDICATE_OPERAND_SCHEMA = _object(
    {
        "source": _STRING,
        "path": _STRING,
        "select": _nullable(
            _object(
                {
                    "list": {"type": "string", "enum": list(SELECT_LISTS)},
                    "key": {"type": "string", "enum": list(SELECT_KEYS)},
                    "value": _STRING,
                }
            )
        ),
    }
)
PLAN_SCHEMA = _object(
    {
        "hypotheses": {
            "type": "array",
            "items": _object(
                {
                    "id": _STRING,
                    "statement": SENTENCE_SCHEMA,
                    "test": _object(
                        {
                            "tool": _STRING,
                            "arguments": _object(
                                {
                                    "metric": _nullable(_STRING),
                                    "direction": _nullable(_STRING),
                                    "top_k": _nullable({"type": "integer"}),
                                    "start": _nullable(_STRING),
                                    "end_exclusive": _nullable(_STRING),
                                    "metrics": _nullable({"type": "array", "items": _STRING}),
                                    "sku": _nullable(_STRING),
                                    "by": _nullable(_STRING),
                                }
                            ),
                        }
                    ),
                    "expect": _object(
                        {
                            "op": {"type": "string", "enum": list(HYPOTHESIS_OPS)},
                            "a": PREDICATE_OPERAND_SCHEMA,
                            "b": _nullable(PREDICATE_OPERAND_SCHEMA),
                            "threshold": _nullable(_STRING),
                            "k": _nullable({"type": "integer"}),
                        }
                    ),
                }
            ),
        }
    }
)
PATCH_SCHEMA = _object(
    {
        "patches": {
            "type": "array",
            "items": _object(
                {
                    "at": _STRING,
                    "sentence": _nullable(SENTENCE_SCHEMA),
                    "text": _nullable(_STRING),
                    "ids": _nullable({"type": "array", "items": _STRING}),
                }
            ),
        }
    }
)
REVIEW_SCHEMA = _object(
    {
        "issues": {
            "type": "array",
            "items": _object(
                {
                    "at": _STRING,
                    "code": {"type": "string", "enum": list(REVIEW_CODES)},
                    "note": _STRING,
                }
            ),
        }
    }
)
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


def with_definitions(schema):
    """Replace every inline sentence and binding with a reference to one shared definition.

    Providers compile strict schemas into a grammar; the report schema repeats sentences in many
    places and Anthropic rejects the inlined form as too large, so it is sent with ``$defs``.
    """
    binding_ref, sentence_ref = {"$ref": "#/$defs/binding"}, {"$ref": "#/$defs/sentence"}

    def visit(value):
        if value == SENTENCE_SCHEMA:
            return sentence_ref
        if isinstance(value, dict):
            return {k: visit(v) for k, v in value.items()}
        if isinstance(value, list):
            return [visit(v) for v in value]
        return value

    sentence = {**SENTENCE_SCHEMA, "properties": {**SENTENCE_SCHEMA["properties"]}}
    sentence["properties"]["bindings"] = {"type": "array", "items": binding_ref}
    return {**visit(schema), "$defs": {"sentence": sentence, "binding": BINDING_SCHEMA}}


def output_schema(kind):
    if kind in {"plan", "patch", "review"}:
        return {"plan": PLAN_SCHEMA, "patch": PATCH_SCHEMA, "review": REVIEW_SCHEMA}[kind]
    return with_definitions(_inline_schema(kind))


def _inline_schema(kind):
    if kind == "report":
        return _object(
            {
                "summary": {"type": "array", "items": SENTENCE_SCHEMA},
                "findings": {"type": "array", "items": FINDING_SCHEMA},
                "recommendations": {"type": "array", "items": RECOMMENDATION_SCHEMA},
                "ruled_out": {"type": "array", "items": RULED_OUT_SCHEMA},
            }
        )
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
