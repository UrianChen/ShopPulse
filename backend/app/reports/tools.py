"""Read-only analysis tools over a frozen report context. No model code, SQL or network.

Every call produces an evidence record (arguments, hashes, versions) that sentence bindings can
reference. Drill-down tools that need order lines receive a server-side ``drill`` callback; the
model process never touches the database.
"""

import hashlib
import json
import uuid
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.reports.anomalies import anomalies
from app.reports.grammar import LABELS as GRAMMAR_LABELS
from app.reports.schema import BUDGETS, SKU_MIN_ORDERS, TOOL_VERSION, HypothesisSpec

__all__ = ["anomalies"]

LABELS = {
    key: GRAMMAR_LABELS["metric"]["zh"][key]
    for key in (
        "net_sales",
        "paid_orders",
        "aov",
        "gross_profit",
        "gross_margin",
        "refund_amount_rate",
        "gross_sales",
        "refund_amount",
        "net_cogs",
        "paid_units",
    )
}
LIMITATIONS = {
    "zh": [
        "未提供广告、流量、库存数据，不能评估投放效果、转化率或补货数量。",
        "观察到的变化不能证明原因；模型提出的原因均为待验证假设。",
        "订单按支付时间归期，累计退款反映数据截止时点，比较期的退款观察时长可能不同。",
    ],
    "en": [
        "No advertising, traffic or inventory data is provided, so campaign effect, conversion "
        "and restocking cannot be assessed.",
        "Observed changes do not prove causes; causes proposed by the model are hypotheses.",
        "Orders are assigned by payment time and refunds are cumulative at the data cutoff, so "
        "refund observation windows can differ between periods.",
    ],
}
DEFINITIONS = {
    "zh": {
        "net_sales": "支付订单的商品实付减去这些订单的累计退款，不含运费。",
        "paid_orders": "周期内按支付时间归属的去重订单数。",
        "aov": "净销售额除以支付订单量。",
        "gross_profit": "净销售额减去净商品成本；未扣广告、佣金、运费、人工和税费。",
        "gross_margin": "商品毛利除以净销售额。",
        "refund_amount_rate": "支付订单累计退款除以退款前商品实付。",
        "gross_sales": "支付订单的商品实付合计，未扣退款。",
        "refund_amount": "本期支付订单在数据截止时点的累计退款。",
        "net_cogs": "按发布时成本版本计算的商品成本，扣除已回库数量。",
        "paid_units": "支付订单中的商品件数。",
        "gross_aov": "退款前商品实付除以支付订单量。",
        "refunded_order_rate": "发生退款的订单占支付订单的比例。",
        "cost_line_coverage": "有成本的订单明细占全部明细的比例。",
        "cost_amount_coverage": "有成本的明细实付占全部实付的比例。",
    },
    "en": {
        "net_sales": "Paid product amounts minus cumulative refunds on those orders, "
        "excluding shipping.",
        "paid_orders": "Distinct orders assigned to the period by payment time.",
        "aov": "Net sales divided by paid orders.",
        "gross_profit": "Net sales minus net cost of goods; advertising, commission, shipping, "
        "labour and tax are not deducted.",
        "gross_margin": "Product gross profit divided by net sales.",
        "refund_amount_rate": "Cumulative refunds on paid orders divided by paid sales before "
        "refunds.",
        "gross_sales": "Paid product amounts before refunds.",
        "refund_amount": "Cumulative refunds at the data cutoff for orders paid in the period.",
        "net_cogs": "Cost of goods from the cost version frozen at publication, net of "
        "restocked units.",
        "paid_units": "Units on paid orders.",
        "gross_aov": "Paid sales before refunds divided by paid orders.",
        "refunded_order_rate": "Share of paid orders with a refund.",
        "cost_line_coverage": "Share of order lines with a known cost.",
        "cost_amount_coverage": "Share of paid amount on lines with a known cost.",
    },
}
KEY_METRICS = (
    "net_sales",
    "paid_orders",
    "paid_units",
    "aov",
    "gross_profit",
    "gross_margin",
    "refund_amount",
    "refund_amount_rate",
)
CORE = (
    "get_data_quality",
    "calculate_metrics",
    "get_sales_trend",
    "rank_products",
    "compare_periods",
    "decompose_sales_change",
    "detect_anomalies",
)
MetricName = Literal[
    "gross_sales",
    "refund_amount",
    "net_sales",
    "paid_orders",
    "paid_units",
    "aov",
    "gross_aov",
    "net_cogs",
    "gross_profit",
    "gross_margin",
    "refund_amount_rate",
    "refunded_order_rate",
    "cost_line_coverage",
    "cost_amount_coverage",
]


def limitations(language="zh"):
    return list(LIMITATIONS.get(language, LIMITATIONS["zh"]))


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


class ToolError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class NoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RankArgs(NoArgs):
    metric: Literal["net_sales", "gross_profit", "refund_amount", "paid_units"] = "net_sales"
    direction: Literal["asc", "desc"] = "desc"
    top_k: int = Field(default=10, ge=1, le=50, strict=True)


class TrendArgs(NoArgs):
    start: date | None = None
    end_exclusive: date | None = None
    metrics: list[MetricName] = Field(default_factory=list, max_length=6)


class CompareArgs(NoArgs):
    metrics: list[MetricName] = Field(default_factory=list, max_length=14)


class SkuArgs(NoArgs):
    sku: str = Field(min_length=1, max_length=128)


class RefundArgs(NoArgs):
    by: Literal["sku", "day"] = "sku"
    top_k: int = Field(default=5, ge=1, le=10, strict=True)


class CostArgs(NoArgs):
    top_k: int = Field(default=5, ge=1, le=10, strict=True)


class MetricArgs(NoArgs):
    metric: MetricName


class DecomposeArgs(NoArgs):
    metric: Literal["gross_margin", "refund_amount_rate", "aov"]


class DeriveOperandArgs(NoArgs):
    evidence_id: str = Field(min_length=1, max_length=64)
    path: str = Field(min_length=1, max_length=160, pattern=r"^[a-z0-9_.]+$")


class DeriveArgs(NoArgs):
    op: Literal["diff", "ratio", "multiple", "share"]
    a: DeriveOperandArgs
    b: DeriveOperandArgs


class HypothesisArgs(HypothesisSpec):
    wave: int = Field(default=1, ge=0, le=3)
    statement: dict | None = None
    statement_text: str | None = Field(default=None, max_length=400)


class RecheckItem(NoArgs):
    id: str = Field(max_length=40)
    statement: str | None = Field(default=None, max_length=400)
    previous_state: Literal["supported", "refuted", "inconclusive"]
    source_report_id: str = Field(max_length=64)
    spec: dict


class RecheckArgs(NoArgs):
    items: list[RecheckItem] = Field(max_length=5)


TOOLS = {
    "get_data_quality": NoArgs,
    "calculate_metrics": NoArgs,
    "get_sales_trend": TrendArgs,
    "rank_products": RankArgs,
    "compare_periods": CompareArgs,
    "decompose_sales_change": NoArgs,
    "detect_anomalies": NoArgs,
    "inspect_sku": SkuArgs,
    "refund_breakdown": RefundArgs,
    "cost_coverage": CostArgs,
    "explain_metric": MetricArgs,
    "check_recommendation": NoArgs,
    "get_merchant_notes": NoArgs,
    "decompose_metric_change": DecomposeArgs,
    "get_history": NoArgs,
    "derive": DeriveArgs,
}
# Run by the server only (hypothesis verdicts and rechecks); never offered to the model.
INTERNAL = {"test_hypothesis": HypothesisArgs, "recheck_hypotheses": RecheckArgs}
DESCRIPTIONS = {
    "get_data_quality": "Coverage, quality warnings and excluded rows for the frozen scope.",
    "calculate_metrics": "Current and comparison period metrics.",
    "get_sales_trend": "Daily trend points; optionally a date sub-range inside the report "
    "period and a metric subset.",
    "rank_products": "Products ranked by a metric (asc/desc).",
    "compare_periods": "Deltas, change rates and comparability states between periods.",
    "decompose_sales_change": "Descriptive product, order-count and order-value contributions "
    "to the net sales change.",
    "detect_anomalies": "Deterministic anomaly rules with thresholds, states and items.",
    "inspect_sku": "Drill into one SKU: both periods, comparison and its daily trend.",
    "refund_breakdown": "Largest refunds by SKU (with comparison-period values and the change "
    "in each SKU's refund share) or by day.",
    "cost_coverage": "Products whose cost is missing, by sales impact.",
    "explain_metric": "Server definition of a metric (no values).",
    "check_recommendation": "Earlier recommendations due for review with baseline and current "
    "values of their verification metric.",
    "get_merchant_notes": "Merchant notes (promotions, holidays, stockouts, price changes) "
    "overlapping the report periods.",
    "decompose_metric_change": "Split the change of gross_margin or refund_amount_rate into "
    "product-mix and per-product rate effects (percentage points, by SKU), or the change of aov "
    "into price-per-unit and units-per-order effects.",
    "get_history": "Store-level metrics for the earlier windows of the same length (newest "
    "first) and how many consecutive periods each metric has moved in one direction.",
    "derive": "Compute diff, ratio, multiple or share of two values you were given "
    "(evidence_id and path each). Usually a computed binding is simpler.",
}


def metric_subset(metrics, keys):
    return {k: metrics[k] for k in keys if k in metrics}


def _orders(value):
    try:
        return int(Decimal(str(value))) if value is not None else 0
    except ArithmeticError:
        return 0


def sample_level(current_orders, previous_orders=None, compared=True):
    """Return "low" when a SKU-level comparison rests on few orders.

    With a comparison the larger period decides: a fall from many orders to almost none is a real
    change, while three orders against one is noise.
    """
    orders = _orders(current_orders)
    if compared:
        orders = max(orders, _orders(previous_orders))
    return "low" if orders < SKU_MIN_ORDERS else "ok"


def with_sample(product):
    """Product payload plus a small-sample flag for its period comparison."""
    previous = product.get("previous")
    return {
        **product,
        "sample": sample_level(
            product["current"]["metrics"]["paid_orders"]["value"] if product.get("current") else 0,
            previous["metrics"]["paid_orders"]["value"] if previous else None,
            previous is not None,
        ),
    }


def flag_items(items):
    return [
        {
            **item,
            "sample": sample_level(
                item.get("orders_current"),
                item.get("orders_previous"),
                item.get("orders_previous") is not None,
            ),
        }
        for item in items
    ]


STREAK_KEYS = ("net_sales", "paid_orders", "aov", "gross_margin", "refund_amount_rate")


def _unavailable_metric(metric):
    return {
        "value": None,
        "unit": metric["unit"],
        "quality": "unavailable",
        "unavailable_reason": "INCOMPLETE_COVERAGE",
    }


def history_payload(raw, result, window_days):
    """Frozen history evidence: windows newest first and per-metric direction streaks."""
    windows = []
    for window in reversed(raw["windows"]):
        metrics = window["metrics"]
        if not window["coverage_complete"]:
            metrics = {k: _unavailable_metric(m) for k, m in metrics.items()}
        windows.append({**window, "metrics": metrics})
    streaks = {}
    current = result["current"]
    if current["coverage_complete"]:
        for key in STREAK_KEYS:
            series = [current["metrics"][key]["value"]]
            for window in windows:
                series.append(window["metrics"][key]["value"])
            direction, periods = None, 0
            for newer, older in zip(series, series[1:], strict=False):
                if newer is None or older is None:
                    break
                step = Decimal(newer) - Decimal(older)
                here = "up" if step > 0 else "down" if step < 0 else "flat"
                if direction not in (None, here):
                    break
                direction, periods = here, periods + 1
            if direction is not None:
                streaks[key] = {"direction": direction, "periods": periods}
    return {"window_days": window_days, "windows": windows, "streaks": streaks}


class ToolRegistry:
    def __init__(
        self,
        context,
        report_id,
        run_id,
        evidence=None,
        drill=None,
        cache=None,
        limit=BUDGETS["tools"],
        include_names=False,
        test_limit=BUDGETS["tests"],
    ):
        self.context, self.report_id, self.run_id = context, report_id, run_id
        self.evidence = list(evidence or [])
        self.drill = drill
        self.cache = dict(cache or {})
        self.limit = limit
        self.calls = 0
        self.include_names = include_names
        self.test_limit = test_limit
        self.tests = 0

    def known(self):
        """Every evidence record this registry can reference (current list and cache)."""
        seen = {e["evidence_id"]: e for e in self.cache.values()}
        seen.update({e["evidence_id"]: e for e in self.evidence})
        return list(seen.values())

    def lookup(self, evidence_id):
        return next((e for e in self.known() if e["evidence_id"] == evidence_id), None)

    def scope_dates(self):
        query = self.context["result"]["query"]
        return date.fromisoformat(query["start"]), date.fromisoformat(query["end_exclusive"])

    def compute(self, name, parsed):
        ctx = self.context
        result = ctx["result"]
        language = ctx.get("language", "zh")
        if name == "calculate_metrics":
            return {"current": result["current"], "previous": result["previous"]}
        if name == "get_data_quality":
            return {
                "warnings": result["warnings"],
                "quality": result["current"]["quality"],
                "excluded_rows": result["excluded_rows"],
                "coverage_complete": result["current"]["coverage_complete"],
            }
        if name == "get_sales_trend":
            start, end = self.scope_dates()
            lo = date.fromisoformat(parsed["start"]) if parsed["start"] else start
            hi = date.fromisoformat(parsed["end_exclusive"]) if parsed["end_exclusive"] else end
            if not start <= lo < hi <= end:
                raise ToolError("OUT_OF_SCOPE")
            points = [
                p
                for p in result["trend"]
                if lo <= date.fromisoformat(p["start"])
                and date.fromisoformat(p["end_exclusive"]) <= hi
            ]
            if parsed["metrics"]:
                points = [
                    {
                        "start": p["start"],
                        "end_exclusive": p["end_exclusive"],
                        "coverage_complete": p["coverage_complete"],
                        "metrics": metric_subset(p["metrics"], parsed["metrics"]),
                    }
                    for p in points
                ]
            return {"points": points}
        if name == "rank_products":
            key = f"{parsed['metric']}:{parsed['direction']}"
            return {
                "items": [with_sample(p) for p in ctx["rankings"][key][: parsed["top_k"]]],
                "total": result["product_count"],
            }
        if name == "compare_periods":
            comparison = result["comparison"]
            if comparison is not None and parsed["metrics"]:
                comparison = metric_subset(comparison, parsed["metrics"])
            return {"comparison": comparison}
        if name == "decompose_sales_change":
            contributions = result["contributions"]
            return {
                **contributions,
                "gainers": flag_items(contributions["gainers"]),
                "decliners": flag_items(contributions["decliners"]),
            }
        if name == "decompose_metric_change":
            decomposition = (result.get("decompositions") or {}).get(parsed["metric"])
            if decomposition is None:
                raise ToolError("DECOMPOSITION_UNAVAILABLE")
            return {**decomposition, "items": flag_items(decomposition["items"])}
        if name == "get_history":
            if not ctx.get("history"):
                raise ToolError("HISTORY_UNAVAILABLE")
            return ctx["history"]
        if name == "derive":
            from app.reports.derive import DeriveError, compute, operand, public

            sources = []
            for side in ("a", "b"):
                ev = self.lookup(parsed[side]["evidence_id"])
                if ev is None:
                    raise ToolError("UNKNOWN_EVIDENCE")
                try:
                    sources.append(operand(ev, parsed[side]["path"]))
                except DeriveError as error:
                    raise ToolError("DERIVE_" + error.code) from None
            try:
                value = compute(parsed["op"], *sources)
            except DeriveError as error:
                raise ToolError("DERIVE_" + error.code) from None
            return {
                "op": parsed["op"],
                "a": public(sources[0]),
                "b": public(sources[1]),
                "result": value,
            }
        if name == "test_hypothesis":
            from app.reports.hypothesis import run_test

            return run_test(self, parsed)
        if name == "recheck_hypotheses":
            from app.reports.hypothesis import recheck

            return recheck(self, parsed)
        if name == "detect_anomalies":
            return anomalies(
                result, ctx["rankings"], ctx["stats"], ctx["rules"], ctx.get("language", "zh")
            )
        if name == "inspect_sku":
            scoped = result["query"]["skus"]
            if scoped and parsed["sku"] not in scoped:
                raise ToolError("OUT_OF_SCOPE")
            if self.drill is None:
                raise ToolError("DRILL_UNAVAILABLE")
            return with_sample(self.drill(parsed["sku"]))
        if name == "refund_breakdown":
            keys = ("refund_amount", "refund_amount_rate", "gross_sales", "net_sales")
            if parsed["by"] == "sku":
                items = [
                    {
                        "sku": p["sku"],
                        "product_name": p["product_name"],
                        "metrics": metric_subset(p["current"]["metrics"], keys),
                        "previous": {"metrics": metric_subset(p["previous"]["metrics"], keys)}
                        if p.get("previous")
                        else None,
                        "comparison": metric_subset(p["comparison"], keys)
                        if p.get("comparison")
                        else None,
                        "sample": with_sample(p)["sample"],
                    }
                    for p in ctx["rankings"]["refund_amount:desc"]
                    if p["current"]["metrics"]["refund_amount"]["value"] not in (None, "0")
                ]
            else:
                points = [
                    p
                    for p in result["trend"]
                    if p["metrics"]["refund_amount"]["value"] not in (None, "0")
                ]
                points.sort(
                    key=lambda p: (-int(p["metrics"]["refund_amount"]["value"]), p["start"])
                )
                items = [
                    {"start": p["start"], "metrics": metric_subset(p["metrics"], keys)}
                    for p in points
                ]
            previous = result.get("previous")
            return {
                "by": parsed["by"],
                "items": items[: parsed["top_k"]],
                "total": {
                    "metrics": metric_subset(result["current"]["metrics"], keys),
                    "previous": {"metrics": metric_subset(previous["metrics"], keys)}
                    if previous
                    else None,
                    "comparison": metric_subset(result["comparison"], keys)
                    if result.get("comparison")
                    else None,
                },
            }
        if name == "cost_coverage":
            return {
                "summary": result["current"]["quality"],
                "items": [
                    {
                        "sku": p["sku"],
                        "product_name": p["product_name"],
                        "missing_cost_rows": p["current"]["quality"]["missing_cost_rows"],
                        "metrics": metric_subset(p["current"]["metrics"], ("net_sales",)),
                    }
                    for p in ctx.get("missing_cost", [])[: parsed["top_k"]]
                ],
            }
        if name == "explain_metric":
            metric = parsed["metric"]
            return {
                "metric": metric,
                "label": GRAMMAR_LABELS["metric"][language][metric],
                "definition": DEFINITIONS[language][metric],
                "unit": ctx["result"]["current"]["metrics"][metric]["unit"],
            }
        if name == "check_recommendation":
            return {"items": ctx.get("followups", [])}
        return {"items": ctx.get("notes", [])}

    def execute(self, name, args, core=False):
        if name == "get_evidence":
            # The model process fetches a test's evidence after a verdict; nothing is computed.
            found = self.lookup(str((args or {}).get("evidence_id")))
            if found is None:
                raise ToolError("UNKNOWN_EVIDENCE")
            return found
        internal = name in INTERNAL
        if name not in TOOLS and not internal:
            raise ToolError("TOOL_NOT_ALLOWED")
        if not core and internal and self.tests >= self.test_limit:
            raise ToolError("TEST_BUDGET")
        if not core and not internal and self.calls >= self.limit:
            raise ToolError("TOOL_BUDGET")
        try:
            parsed = (
                (INTERNAL.get(name) or TOOLS.get(name))
                .model_validate(args or {})
                .model_dump(mode="json")
            )
        except ValidationError:
            raise ToolError("INVALID_ARGUMENTS") from None
        if not core and internal:
            self.tests += 1
        elif not core:
            self.calls += 1
        args_hash = digest(parsed)
        cached = self.cache.get((name, args_hash))
        if cached is not None:
            if all(e["evidence_id"] != cached["evidence_id"] for e in self.evidence):
                self.evidence.append(cached)
            return cached
        payload = self.compute(name, parsed)
        result = self.context["result"]
        evidence = {
            "evidence_id": str(uuid.uuid4()),
            "report_id": self.report_id,
            "run_id": self.run_id,
            "dataset_id": result["dataset_id"],
            "scope": result["query"],
            "tool": name,
            "tool_version": TOOL_VERSION,
            "metric_definition_version": result["metric_definition_version"],
            "engine_version": result["engine_version"],
            "args": parsed,
            "args_hash": args_hash,
            "payload": payload,
            "result_hash": digest(payload),
        }
        self.cache[(name, args_hash)] = evidence
        self.evidence.append(evidence)
        return evidence

    def core(self):
        names = list(CORE)
        if self.context.get("followups"):
            names.append("check_recommendation")
        if self.context.get("notes"):
            names.append("get_merchant_notes")
        if self.context.get("history"):
            names.append("get_history")
        return {name: self.execute(name, {}, core=True) for name in names}


HIDDEN = {"order_id", "source_row_number", "unavailable_reason", "row_count"}


def project(value, include_names, cap=10, metric_keys=KEY_METRICS, key=None, drop=frozenset()):
    """Model-facing view of a payload. Truncation and dropped keys keep remaining paths valid."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k in HIDDEN or k in drop:
                continue
            if k == "product_name" and not include_names:
                continue
            if k in {"metrics", "comparison"} and isinstance(v, dict) and metric_keys:
                v = {m: v[m] for m in metric_keys if m in v}
            out[k] = project(v, include_names, cap, metric_keys, k, drop)
        return out
    if isinstance(value, list):
        # Rule checks and warnings are short fixed lists the model must always see in full.
        limit = (
            None
            if key in {"checks", "warnings", "data_warnings"}
            else 31
            if key in {"points", "trend", "windows"}
            else cap
        )
        return [project(v, include_names, cap, metric_keys, key, drop) for v in value[:limit]]
    if isinstance(value, str):
        return value[:160]
    return value


def wire(value, include_names):
    """Backwards-compatible projection helper (v1 name)."""
    return project(value, include_names, cap=5, metric_keys=None)


SHRINK = (
    (10, frozenset()),
    (5, frozenset()),
    (5, frozenset({"previous", "quality"})),
    (3, frozenset({"previous", "quality", "comparison"})),
    (2, frozenset({"previous", "quality", "comparison", "points", "trend"})),
)


def tool_message(evidence, include_names, max_bytes=12000):
    name = evidence["tool"]
    keys = None if name in {"calculate_metrics", "compare_periods"} else KEY_METRICS
    stages = SHRINK[:2] if name in {"calculate_metrics", "compare_periods"} else SHRINK
    for cap, drop in stages:
        body = {
            "evidence_id": evidence["evidence_id"],
            "tool": name,
            "args": evidence["args"],
            "data": project(evidence["payload"], include_names, cap, keys, drop=drop),
        }
        text = json.dumps(body, ensure_ascii=False)
        if len(text.encode()) <= max_bytes:
            return text
    return json.dumps(
        {
            "evidence_id": evidence["evidence_id"],
            "tool": name,
            "note": "Result too large to show; narrow the arguments.",
        }
    )


def compact_message(evidence):
    """Short digest used when older tool results are compacted out of the context."""
    payload = evidence["payload"]
    digest_items = []
    for key in ("items", "points", "gainers", "decliners", "checks", "windows"):
        if isinstance(payload.get(key), list):
            for i, item in enumerate(payload[key][:3]):
                entry = {"path": f"{key}.{i}"}
                for field in ("sku", "start", "code", "state"):
                    if field in item:
                        entry[field] = item[field]
                digest_items.append(entry)
    return json.dumps(
        {
            "evidence_id": evidence["evidence_id"],
            "tool": evidence["tool"],
            "compacted": True,
            "first_items": digest_items[:6],
        },
        ensure_ascii=False,
    )


def fact(evidence_id, period, key, metric, language="zh"):
    fmt = {"minor_currency": "money", "count": "count", "ratio": "percent"}[metric["unit"]]
    label = GRAMMAR_LABELS["metric"][language][key]
    if language == "en":
        name = "current" if period == "current" else "comparison"
        template = f"{label[0].upper() + label[1:]} in the {name} period: {{{{value}}}}."
    else:
        template = ("本期" if period == "current" else "比较期") + label + "为 {{value}}。"
    return {
        "template": template,
        "bindings": [
            {
                "name": "value",
                "evidence_id": evidence_id,
                "path": f"{period}.metrics.{key}",
                "format": fmt,
            }
        ],
    }


def metric_facts(evidence, language="zh"):
    facts = []
    for ev in evidence:
        if ev["tool"] != "calculate_metrics":
            continue
        for period in ("current", "previous"):
            data = ev["payload"].get(period)
            if not data:
                continue
            for key in LABELS:
                metric = data["metrics"][key]
                if metric["value"] is None:
                    continue
                facts.append(fact(ev["evidence_id"], period, key, metric, language))
    return facts


TOPIC_KEYS = {
    "refund_review": ("refund_amount", "refund_amount_rate", "gross_sales", "net_sales"),
    "profit_review": ("gross_profit", "gross_margin", "net_cogs", "net_sales"),
}


def topic_facts(evidence, intent, language="zh"):
    keys = TOPIC_KEYS.get(intent, ("net_sales", "paid_orders", "aov", "gross_profit"))
    facts = metric_facts(evidence, language)
    return [
        f for key in keys for f in facts if f["bindings"][0]["path"] == f"current.metrics.{key}"
    ]
