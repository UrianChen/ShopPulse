"""Scripted policies for offline evaluation.

``reference`` behaves like a careful analyst: it reads the anomaly checks, drills into the
products behind them and writes evidence-bound findings. It is deterministic, so the offline suite
measures the pipeline (tools, grammar, validation, loop limits) and gates regressions in CI. Model
quality is measured by the live suite against a real provider.
"""

import json

from app.providers.mock_server import from_neutral, respond, to_neutral, tool_results
from app.reports.grammar import LABELS

TOPIC = {
    "SALES_CHANGE": "sales",
    "HIGH_REFUND": "refund",
    "MARGIN_DROP": "cost",
    "NEGATIVE_PROFIT": "product",
    "CONCENTRATION": "product",
    "DAILY_MAD": "period",
}
PRIORITY = [
    "NEGATIVE_PROFIT",
    "HIGH_REFUND",
    "MARGIN_DROP",
    "SALES_CHANGE",
    "DAILY_MAD",
    "CONCENTRATION",
]
METRIC = {
    "sales": "net_sales",
    "refund": "refund_amount_rate",
    "cost": "gross_profit",
    "product": "net_sales",
    "period": "net_sales",
    "quality": "gross_profit",
}
TEXT = {
    "zh": {
        "rule": "{{rule}}检查结果为{{state}}。",
        "refund": "退款最多的商品是 {{sku}}，累计退款为 {{amount}}。",
        "decline": "对净销售额拖累最大的商品是 {{sku}}，贡献为 {{amount}}。",
        "gain": "对净销售额拉动最大的商品是 {{sku}}，贡献为 {{amount}}。",
        "loss": "毛利为负的商品包括 {{sku}}，商品毛利为 {{amount}}。",
        "share": "销售最集中的头部商品合计占比为 {{share}}。",
        "day": "离群日期为 {{day}}。",
        "margin": "商品毛利率变化 {{pp}}。",
        "drill": "{{sku}} 本期净销售额为 {{sales}}，累计退款为 {{refund}}。",
        "drill_change": "{{sku}} 的净销售额较比较期变化 {{change}}。",
        "cost": "缺少成本的商品包括 {{sku}}，其净销售额为 {{sales}}。",
        "top": "本期净销售额最高的商品是 {{sku}}，净销售额为 {{sales}}。",
        "change": "净销售额较比较期变化 {{change}}。",
        "note": "可能与商家记录的{{kind}}有关：{{note}}。",
        "hyp": "变化原因仍需结合订单明细核查。",
        "act_sku": "复核 {{sku}} 的价格、退款原因和成本记录",
        "act": "复核本期数据覆盖、退款与成本记录",
        "cost_title": "成本覆盖",
        "sales_title": "销售变化",
    },
    "en": {
        "rule": "The {{rule}} check is {{state}}.",
        "refund": "The product with the most refunds is {{sku}} at {{amount}}.",
        "decline": "The largest drag on net sales is {{sku}} at {{amount}}.",
        "gain": "The largest contributor to net sales is {{sku}} at {{amount}}.",
        "loss": "Products with negative margin include {{sku}} at {{amount}}.",
        "share": "The leading products account for {{share}} of sales.",
        "day": "The outlier day is {{day}}.",
        "margin": "Product gross margin changed by {{pp}}.",
        "drill": "{{sku}} had net sales of {{sales}} and refunds of {{refund}}.",
        "drill_change": "Net sales of {{sku}} changed by {{change}} against the comparison period.",
        "cost": "Products without costs include {{sku}} with net sales of {{sales}}.",
        "top": "The best-selling product is {{sku}} with net sales of {{sales}}.",
        "change": "Net sales changed by {{change}} against the comparison period.",
        "note": "This may relate to the merchant's {{kind}} note {{note}}.",
        "hyp": "The cause still needs checking against order details.",
        "act_sku": "Review pricing, refund reasons and cost records for {{sku}}",
        "act": "Review data coverage, refunds and cost records for this period",
        "cost_title": "Cost coverage",
        "sales_title": "Sales change",
    },
}


def bind(template, *items):
    return {
        "template": template,
        "bindings": [{"name": n, "evidence_id": e, "path": p, "format": f} for n, e, p, f in items],
    }


def by_tool(entries):
    found = {}
    for entry in entries:
        if isinstance(entry, dict) and entry.get("tool") and entry.get("evidence_id"):
            found.setdefault(entry["tool"], entry)
    return found


def has(data, *path):
    value = data
    for key in path:
        if isinstance(value, list):
            if not isinstance(key, int) or key >= len(value):
                return False
            value = value[key]
        elif isinstance(value, dict) and key in value:
            value = value[key]
        else:
            return False
    if isinstance(value, dict) and "value" in value:
        return value["value"] is not None
    return value is not None


def reference_turn(messages, flags):
    data = json.loads(messages[1]["content"])
    text = TEXT[data.get("language", "zh")]
    initial = by_tool(data["evidence"])
    results = tool_results(messages)
    tools = by_tool(results)
    rounds = sum(1 for m in messages if m["role"] == "assistant" and m.get("tool_calls"))
    repaired = any("failed validation" in str(m.get("content") or "") for m in messages)
    anomalies = (initial.get("detect_anomalies") or {}).get("data") or {}
    checks = anomalies.get("checks") or []
    triggered = sorted(
        [(i, c) for i, c in enumerate(checks) if c.get("state") == "triggered"],
        key=lambda item: PRIORITY.index(item[1]["code"]),
    )
    warnings = ((initial.get("get_data_quality") or {}).get("data") or {}).get("warnings") or []
    decompose = initial.get("decompose_sales_change") or {}
    open_tools = flags["tools"] and not flags["tool_choice_none"] and not repaired
    if open_tools and rounds == 0:
        calls = []
        if any(c["code"] == "HIGH_REFUND" for _, c in triggered):
            calls.append(
                {
                    "id": "r_refunds",
                    "name": "refund_breakdown",
                    "arguments": {"by": "sku", "top_k": 3},
                }
            )
        if "COST_MISSING" in warnings:
            calls.append({"id": "r_cost", "name": "cost_coverage", "arguments": {"top_k": 3}})
        if not calls:
            calls.append(
                {
                    "id": "r_rank",
                    "name": "rank_products",
                    "arguments": {"metric": "net_sales", "direction": "desc", "top_k": 3},
                }
            )
        return None, calls
    if open_tools and rounds == 1:
        target = None
        codes = {c["code"] for _, c in triggered}
        refunds = ((tools.get("refund_breakdown") or {}).get("data") or {}).get("items") or []
        decliners = (decompose.get("data") or {}).get("decliners") or []
        negative = next((c for _, c in triggered if c["code"] == "NEGATIVE_PROFIT"), None)
        if "HIGH_REFUND" in codes and refunds:
            target = refunds[0]["sku"]
        elif negative and (negative.get("values") or {}).get("items"):
            target = negative["values"]["items"][0]["sku"]
        elif decliners:
            target = decliners[0]["sku"]
        elif refunds:
            target = refunds[0]["sku"]
        if target:
            return None, [{"id": "r_sku", "name": "inspect_sku", "arguments": {"sku": target}}]
    facts = data["fact_examples"]
    findings, recommendations = [], []
    compare = initial.get("compare_periods") or {}
    sales_support = []
    if has(compare.get("data") or {}, "comparison", "net_sales", "change_rate"):
        sales_support.append(
            bind(
                text["change"],
                ("change", compare["evidence_id"], "comparison.net_sales.change_rate", "percent"),
            )
        )
    ranked = tools.get("rank_products") or {}
    if has(ranked.get("data") or {}, "items", 0, "current", "metrics", "net_sales"):
        sales_support.append(
            bind(
                text["top"],
                ("sku", ranked["evidence_id"], "items.0.sku", "entity"),
                ("sales", ranked["evidence_id"], "items.0.current.metrics.net_sales", "money"),
            )
        )
    findings.append(
        {
            "id": "f_sales",
            "topic": "sales",
            "title": text["sales_title"],
            "observation": facts[0],
            "supporting": sales_support,
            "hypotheses": [bind(text["hyp"])],
        }
    )
    detect_id = (initial.get("detect_anomalies") or {}).get("evidence_id")
    refund_items = ((tools.get("refund_breakdown") or {}).get("data") or {}).get("items") or []
    decompose_data = decompose.get("data") or {}
    for index, check in triggered[:3]:
        code = check["code"]
        support = []
        values = check.get("values") or {}
        if code == "HIGH_REFUND" and refund_items:
            ev = tools["refund_breakdown"]["evidence_id"]
            support.append(
                bind(
                    text["refund"],
                    ("sku", ev, "items.0.sku", "entity"),
                    ("amount", ev, "items.0.metrics.refund_amount", "money"),
                )
            )
        elif code == "SALES_CHANGE":
            side = "decliners" if decompose_data.get("decliners") else "gainers"
            if decompose_data.get(side):
                support.append(
                    bind(
                        text["decline" if side == "decliners" else "gain"],
                        ("sku", decompose["evidence_id"], f"{side}.0.sku", "entity"),
                        (
                            "amount",
                            decompose["evidence_id"],
                            f"{side}.0.sales_contribution_minor",
                            "money",
                        ),
                    )
                )
        elif code == "NEGATIVE_PROFIT" and values.get("items"):
            support.append(
                bind(
                    text["loss"],
                    ("sku", detect_id, f"checks.{index}.values.items.0.sku", "entity"),
                    (
                        "amount",
                        detect_id,
                        f"checks.{index}.values.items.0.current.metrics.gross_profit",
                        "money",
                    ),
                )
            )
        elif code == "CONCENTRATION" and values.get("top_three_share") is not None:
            support.append(
                bind(
                    text["share"],
                    ("share", detect_id, f"checks.{index}.values.top_three_share", "percent"),
                )
            )
        elif code == "DAILY_MAD" and values.get("items"):
            support.append(
                bind(text["day"], ("day", detect_id, f"checks.{index}.values.items.0.date", "date"))
            )
        elif code == "MARGIN_DROP" and values.get("delta_pp") is not None:
            support.append(
                bind(text["margin"], ("pp", detect_id, f"checks.{index}.values.delta_pp", "pp"))
            )
        findings.append(
            {
                "id": "f_" + code.lower(),
                "topic": TOPIC[code],
                "title": LABELS["rule"][data.get("language", "zh")][code],
                "observation": bind(
                    text["rule"],
                    ("rule", detect_id, f"checks.{index}.code", "label"),
                    ("state", detect_id, f"checks.{index}.state", "label"),
                ),
                "supporting": support,
                "hypotheses": [],
            }
        )
    drill = tools.get("inspect_sku") or {}
    drill_data = drill.get("data") or {}
    if drill_data.get("sku") and has(drill_data, "current", "metrics", "net_sales"):
        ev = drill["evidence_id"]
        support = [
            bind(
                text["drill"],
                ("sku", ev, "sku", "entity"),
                ("sales", ev, "current.metrics.net_sales", "money"),
                ("refund", ev, "current.metrics.refund_amount", "money"),
            )
        ]
        if has(drill_data, "comparison", "net_sales", "change_rate"):
            support.append(
                bind(
                    text["drill_change"],
                    ("sku", ev, "sku", "entity"),
                    ("change", ev, "comparison.net_sales.change_rate", "percent"),
                )
            )
        target = findings[1] if len(findings) > 1 else findings[0]
        target["supporting"] = (target["supporting"] + support)[:3]
    cost = tools.get("cost_coverage") or {}
    cost_items = (cost.get("data") or {}).get("items") or []
    if cost_items and has(cost_items[0], "metrics", "net_sales"):
        findings.append(
            {
                "id": "f_cost_coverage",
                "topic": "quality",
                "title": text["cost_title"],
                "observation": bind(
                    text["cost"],
                    ("sku", cost["evidence_id"], "items.0.sku", "entity"),
                    ("sales", cost["evidence_id"], "items.0.metrics.net_sales", "money"),
                ),
                "supporting": [],
                "hypotheses": [],
            }
        )
    notes = initial.get("get_merchant_notes") or {}
    note_items = (notes.get("data") or {}).get("items") or []
    if note_items:
        findings[0]["hypotheses"].append(
            bind(
                text["note"],
                ("kind", notes["evidence_id"], "items.0.kind", "label"),
                ("note", notes["evidence_id"], "items.0.text", "note"),
            )
        )
    for finding in findings[:4]:
        entity = next(
            (
                b
                for s in [finding["observation"], *finding["supporting"]]
                for b in s["bindings"]
                if b["format"] == "entity"
            ),
            None,
        )
        recommendations.append(
            {
                "action": bind(
                    text["act_sku"], ("sku", entity["evidence_id"], entity["path"], "entity")
                )
                if entity
                else bind(text["act"]),
                "rationale_finding_ids": [finding["id"]],
                "priority": "high"
                if finding["topic"] in {"refund", "cost", "product"}
                else "medium",
                "effort": "small",
                "verification_metric": METRIC.get(finding["topic"], "net_sales"),
                "suggested_review_window": "next_week",
            }
        )
    if data["kind"] == "report":
        final = {
            "summary": facts[:2],
            "findings": findings[:5],
            "recommendations": recommendations[:4],
        }
    else:
        supporting = [s for f in findings for s in f["supporting"]]
        # Prefer sentences that name a product: they answer "which one" questions directly.
        supporting.sort(key=lambda s: not any(b["format"] == "entity" for b in s["bindings"]))
        final = {
            "kind": "answer",
            "answer": facts[:1] + supporting[:2],
            "findings": [],
            "recommendations": [],
            "clarify": None,
            "options": [],
            "suggested_query": None,
        }
    return json.dumps(final, ensure_ascii=False), []


def transport_for(policy):
    """A provider transport implementing a scripted policy over the real wire formats."""

    def transport(url, key, payload, timeout, protocol="openai_chat"):
        if policy == "reference":
            messages, flags = to_neutral(protocol, payload)
            content, calls = reference_turn(messages, flags)
            return from_neutral(protocol, content, calls)
        status, body = respond(protocol, {**payload, "model": policy})
        if status != 200:
            from app.providers.egress import ProviderError

            raise ProviderError("PROVIDER_REJECTED", status)
        return body

    return transport
