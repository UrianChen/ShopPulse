"""Tools consume a frozen metric snapshot, never execute model code or SQL."""

import hashlib
import json
import uuid
from decimal import Decimal, localcontext
from statistics import median
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.reports.schema import RULE_VERSION

LABELS = {
    "net_sales": "净销售额",
    "paid_orders": "支付订单量",
    "aov": "净客单价",
    "gross_profit": "商品毛利",
    "gross_margin": "商品毛利率",
    "refund_amount_rate": "累计退款金额占比",
    "gross_sales": "退款前商品实付",
    "refund_amount": "支付订单累计退款",
    "net_cogs": "净商品成本",
    "paid_units": "支付件数",
}
LIMITATIONS = [
    "未提供广告、流量、库存数据，不能评估投放效果、转化率或补货数量。",
    "观察到的变化不能证明原因；模型提出的原因均为待验证假设。",
    "订单按支付时间归期，累计退款反映数据截止时点，比较期的退款观察时长可能不同。",
]


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def number(metrics, key):
    value = metrics[key]["value"]
    return Decimal(value) if value is not None else None


def anomalies(result, rankings, stats, rules):
    with localcontext() as context:
        context.prec = 70
        return _anomalies(result, rankings, stats, rules)


def _anomalies(result, rankings, stats, rules):
    current, previous = result["current"], result["previous"]
    metrics = current["metrics"]
    orders = number(metrics, "paid_orders") or 0
    enough = current["coverage_complete"] and orders >= rules["min_orders"]
    both = (
        enough
        and previous
        and previous["coverage_complete"]
        and ((number(previous["metrics"], "paid_orders") or 0) >= rules["min_orders"])
    )
    findings, checks = [], []

    def check(code, eligible, triggered, values, limitation):
        state = (
            "triggered" if eligible and triggered else "clear" if eligible else "insufficient_data"
        )
        record = {"code": code, "state": state, "values": values, "limitation": limitation}
        checks.append(record)
        if state == "triggered":
            findings.append(record)

    change = (result["comparison"] or {}).get("net_sales", {}).get("change_rate")
    check(
        "SALES_CHANGE",
        bool(both and change is not None),
        change is not None and abs(Decimal(change)) >= Decimal(str(rules["sales_change"])),
        {"change_rate": change, "threshold": str(rules["sales_change"]), "orders": str(orders)},
        "启发式波动提醒，不是统计显著性或业务恶化的证明。",
    )
    refund = number(metrics, "refund_amount_rate")
    check(
        "HIGH_REFUND",
        enough and refund is not None,
        refund is not None and refund >= Decimal(str(rules["refund_rate"])),
        {
            "rate": str(refund) if refund is not None else None,
            "threshold": str(rules["refund_rate"]),
        },
        "支付订单累计退款，不同周期观察时长不同。",
    )
    margin = (result["comparison"] or {}).get("gross_margin", {}).get("delta_pp")
    complete_cost = (
        metrics["gross_profit"]["quality"] == "confirmed"
        and previous
        and previous["metrics"]["gross_profit"]["quality"] == "confirmed"
    )
    check(
        "MARGIN_DROP",
        bool(both and complete_cost and margin is not None),
        margin is not None and Decimal(margin) <= -Decimal(str(rules["margin_drop_pp"])),
        {"delta_pp": margin, "threshold_pp": str(rules["margin_drop_pp"])},
        "价格、商品结构和成本只能作为描述性线索，需额外证据验证原因。",
    )
    negative = [
        p
        for p in rankings.get("confirmed_negative_profit", rankings["gross_profit:asc"])
        if p["current"]["metrics"]["gross_profit"]["quality"] == "confirmed"
        and (number(p["current"]["metrics"], "gross_profit") or 0) < 0
    ]
    check(
        "NEGATIVE_PROFIT",
        current["coverage_complete"]
        and (bool(negative) or metrics["gross_profit"]["quality"] == "confirmed"),
        bool(negative),
        {
            "items": negative,
            "shown": len(negative),
            "limit": 50,
            "small_sample": orders < rules["min_orders"],
        },
        "只列出成本完整商品，最多展示五十项；小样本不推断长期盈利能力。",
    )
    total = number(metrics, "net_sales")
    top = rankings["net_sales:desc"][:3]
    ratio = (
        sum((number(p["current"]["metrics"], "net_sales") or 0 for p in top), Decimal(0)) / total
        if total and total > 0
        else None
    )
    check(
        "CONCENTRATION",
        current["coverage_complete"]
        and stats["active_skus"] >= 5
        and stats["negative_sales"] == 0
        and stats["unmapped"] == 0
        and ratio is not None,
        ratio is not None and ratio >= Decimal(str(rules["concentration"])),
        {
            "top_three_share": str(ratio) if ratio is not None else None,
            "threshold": str(rules["concentration"]),
            "active_skus": stats["active_skus"],
        },
        "销售集中提醒，不直接断言经营风险已经发生。",
    )
    points, outliers, eligible_days = result["trend"], [], 0
    if result["query"]["granularity"] == "day":
        for i in range(28, len(points)):
            window = points[i - 28 : i]
            if not all(
                p["coverage_complete"] and number(p["metrics"], "net_sales") is not None
                for p in [*window, points[i]]
            ):
                continue
            values = [number(p["metrics"], "net_sales") for p in window]
            center = median(values)
            mad = median([abs(value - center) for value in values])
            if mad == 0:
                continue
            eligible_days += 1
            z = Decimal("0.6745") * (number(points[i]["metrics"], "net_sales") - center) / mad
            if abs(z) >= Decimal(str(rules["mad_z"])):
                outliers.append(
                    {
                        "date": points[i]["start"],
                        "z": str(z),
                        "median": str(center),
                        "mad": str(mad),
                    }
                )
    check(
        "DAILY_MAD",
        eligible_days > 0,
        bool(outliers),
        {
            "items": outliers,
            "eligible_days": eligible_days,
            "threshold": str(rules["mad_z"]),
            "baseline_days": 28,
        },
        "仅使用冻结范围内前置完整日；不足二十八日或 MAD 为零时 insufficient_baseline；"
        "无促销或节假日校正。",
    )
    if not eligible_days:
        checks[-1]["state"] = "insufficient_baseline"
    return {
        "rule_version": RULE_VERSION,
        "thresholds": rules,
        "findings": findings,
        "checks": checks,
        "data_warnings": result["warnings"],
    }


class NoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RankArgs(NoArgs):
    metric: Literal["net_sales", "gross_profit", "refund_amount", "paid_units"] = "net_sales"
    direction: Literal["asc", "desc"] = "desc"
    top_k: int = Field(default=10, ge=1, le=50, strict=True)


TOOLS = {
    name: NoArgs
    for name in (
        "get_data_quality",
        "calculate_metrics",
        "get_sales_trend",
        "compare_periods",
        "decompose_sales_change",
        "detect_anomalies",
    )
}
TOOLS["rank_products"] = RankArgs


class ToolRegistry:
    def __init__(self, context, report_id, run_id, evidence=None):
        self.context, self.report_id, self.run_id = context, report_id, run_id
        self.evidence = list(evidence or [])
        self.calls = 0

    def execute(self, name, args):
        if name not in TOOLS or self.calls >= 8:
            raise ValueError("TOOL_NOT_ALLOWED_OR_BUDGET")
        parsed = TOOLS[name].model_validate(args).model_dump()
        self.calls += 1
        result = self.context["result"]
        if name == "calculate_metrics":
            payload = {"current": result["current"], "previous": result["previous"]}
        elif name == "get_data_quality":
            payload = {
                "warnings": result["warnings"],
                "quality": result["current"]["quality"],
                "excluded_rows": result["excluded_rows"],
                "coverage_complete": result["current"]["coverage_complete"],
            }
        elif name == "get_sales_trend":
            payload = {"points": result["trend"]}
        elif name == "rank_products":
            payload = {
                "items": self.context["rankings"][f"{parsed['metric']}:{parsed['direction']}"][
                    : parsed["top_k"]
                ],
                "total": result["product_count"],
            }
        elif name == "compare_periods":
            payload = {"comparison": result["comparison"]}
        elif name == "decompose_sales_change":
            payload = result["contributions"]
        else:
            payload = anomalies(
                result, self.context["rankings"], self.context["stats"], self.context["rules"]
            )
        evidence = {
            "evidence_id": str(uuid.uuid4()),
            "report_id": self.report_id,
            "run_id": self.run_id,
            "dataset_id": result["dataset_id"],
            "scope": result["query"],
            "tool": name,
            "tool_version": "1.0",
            "metric_definition_version": result["metric_definition_version"],
            "engine_version": result["engine_version"],
            "args": parsed,
            "args_hash": digest(parsed),
            "payload": payload,
            "result_hash": digest(payload),
        }
        self.evidence.append(evidence)
        return evidence

    def core(self):
        return {name: self.execute(name, {}) for name in TOOLS}


def metric_facts(evidence):
    facts = []
    for ev in evidence:
        if ev["tool"] != "calculate_metrics":
            continue
        for period, prefix in (("current", "本期"), ("previous", "比较期")):
            data = ev["payload"].get(period)
            if not data:
                continue
            for key, label in LABELS.items():
                metric = data["metrics"][key]
                if metric["value"] is None:
                    continue
                fmt = {"minor_currency": "money", "count": "count", "ratio": "percent"}[
                    metric["unit"]
                ]
                facts.append(
                    {
                        "text_template": prefix + label + "为 {{value}}。",
                        "bindings": {
                            "value": {
                                "evidence_id": ev["evidence_id"],
                                "path": f"{period}.metrics.{key}",
                                "format": fmt,
                            }
                        },
                    }
                )
    return facts


def topic_facts(evidence, intent):
    keys = {
        "refund_review": ("refund_amount", "refund_amount_rate", "gross_sales", "net_sales"),
        "profit_review": ("gross_profit", "gross_margin", "net_cogs", "net_sales"),
    }.get(intent, ("net_sales", "paid_orders", "aov", "gross_profit"))
    facts = metric_facts(evidence)
    return [
        fact
        for key in keys
        for fact in facts
        if fact["bindings"]["value"]["path"] == f"current.metrics.{key}"
    ]
