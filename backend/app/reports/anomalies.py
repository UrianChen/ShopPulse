"""Deterministic anomaly rules over a frozen metric snapshot (rule version 1.0)."""

from decimal import Decimal, localcontext
from statistics import median

from app.reports.schema import RULE_VERSION


def number(metrics, key):
    value = metrics[key]["value"]
    return Decimal(value) if value is not None else None


ENGLISH_LIMITATIONS = {
    "SALES_CHANGE": "Heuristic swing alert, not proof of statistical significance or decline.",
    "HIGH_REFUND": "Cumulative refunds on paid orders; observation windows differ between periods.",
    "MARGIN_DROP": "Price, product mix and cost are descriptive clues; causes need more evidence.",
    "NEGATIVE_PROFIT": "Lists only products with complete costs, at most fifty; small samples do "
    "not show long-term profitability.",
    "CONCENTRATION": "Concentration alert; it does not assert that a business risk has occurred.",
    "DAILY_MAD": "Uses only complete preceding days inside the frozen scope; fewer than "
    "twenty-eight days or a zero MAD gives insufficient_baseline; no promotion or holiday "
    "adjustment.",
}


def anomalies(result, rankings, stats, rules, language="zh"):
    with localcontext() as context:
        context.prec = 70
        data = _anomalies(result, rankings, stats, rules)
    if language == "en":
        # Findings reference the same check records, so both are translated.
        for check in data["checks"]:
            check["limitation"] = ENGLISH_LIMITATIONS[check["code"]]
    return data


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
