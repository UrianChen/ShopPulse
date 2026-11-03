"""Scripted policies for offline evaluation.

``reference`` behaves like a careful analyst: it reads the anomaly checks, plans hypotheses
about the products behind them (the server tests them), drills one level deeper on what holds and
writes evidence-bound findings that cite supported hypotheses and list refuted ones. It is
deterministic, so the offline suite measures the pipeline (tools, grammar, validation, loop
limits) and gates regressions in CI. Model quality is measured by the live suite against a real
provider.
"""

import json
from decimal import Decimal

from app.providers.mock_server import (
    from_neutral,
    hypothesis,
    operand,
    patch_reply,
    phase_message,
    respond,
    to_neutral,
    tool_results,
    verdicts,
)
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
        "refund_share": "{{sku}} 占全部累计退款的 {{share}}。",
        "times": "本期净销售额是比较期的 {{times}}。",
        "streak": "净销售额已连续 {{periods}} 期{{direction}}。",
        "ruled_out": "该解释的检验结果为{{state}}。",
        "h_refund": "累计退款主要集中在退款最多的商品上。",
        "h_cost": "缺少成本的明细集中在单个商品上。",
        "h_top": "净销售额最高的商品贡献了可观份额。",
        "h_sku_down": "该商品的净销售额较比较期下降。",
        "h_sku_refund": "该商品的累计退款较比较期增加。",
        "cost": "缺少成本的商品包括 {{sku}}，其净销售额为 {{sales}}。",
        "top": "本期净销售额最高的商品是 {{sku}}，净销售额为 {{sales}}。",
        "change": "净销售额较比较期变化 {{change}}。",
        "note": "{{sku}} 的变化可能与商家记录的{{kind}}有关：{{note}}。",
        "h_sku_up": "该商品的净销售额较比较期上升。",
        "h_sku_loss": "该商品本期的商品毛利为负。",
        "margin_sku": "单品毛利率影响最大的商品是 {{sku}}，影响 {{pp}}。",
        "h_margin_sku": "单品毛利率的变化主要集中在单个商品上。",
        "hyp": "变化原因仍需结合订单明细核查。",
        "act_sku": "复核 {{sku}} 的价格、退款原因和成本记录",
        "act": "复核本期数据覆盖、退款与成本记录",
        "cost_title": "成本覆盖",
        "sales_title": "销售变化",
        "followup": "上期建议“{{action}}”的复查结果为{{state}}。",
        "followup_change": "上期建议“{{action}}”的复查结果为{{state}}，{{metric}}变化 {{change}}。",
        "followup_title": "上期建议复查",
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
        "refund_share": "{{sku}} accounts for {{share}} of all refunds.",
        "times": "Net sales this period are {{times}} the comparison period.",
        "streak": "Net sales have been {{direction}} for {{periods}} periods in a row.",
        "ruled_out": "This explanation was tested and is {{state}}.",
        "h_refund": "Refunds sit mainly with the product with the most refunds.",
        "h_cost": "Lines without cost sit mainly with one product.",
        "h_top": "The best-selling product carries a sizeable share of sales.",
        "h_sku_down": "Net sales of this product fell against the comparison period.",
        "h_sku_refund": "Refunds on this product rose against the comparison period.",
        "cost": "Products without costs include {{sku}} with net sales of {{sales}}.",
        "top": "The best-selling product is {{sku}} with net sales of {{sales}}.",
        "change": "Net sales changed by {{change}} against the comparison period.",
        "note": "Changes on {{sku}} may relate to the merchant's {{kind}} note {{note}}.",
        "h_sku_up": "Net sales of this product rose against the comparison period.",
        "h_sku_loss": "This product has negative gross profit this period.",
        "margin_sku": "The product whose own margin moved most is {{sku}}, by {{pp}}.",
        "h_margin_sku": "Product margin changes sit mainly with one product.",
        "hyp": "The cause still needs checking against order details.",
        "act_sku": "Review pricing, refund reasons and cost records for {{sku}}",
        "act": "Review data coverage, refunds and cost records for this period",
        "cost_title": "Cost coverage",
        "sales_title": "Sales change",
        "followup": "The earlier recommendation {{action}} is {{state}}.",
        "followup_change": "The earlier recommendation {{action}} is {{state}}: {{metric}} "
        "changed by {{change}}.",
        "followup_title": "Earlier recommendations",
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


def reference_plan(data, text, triggered, warnings, initial):
    """Hypotheses mirroring the v2 first tool round, as server-tested statements."""
    planned = []
    if any(c["code"] == "HIGH_REFUND" for _, c in triggered):
        planned.append(
            hypothesis(
                "h_ref_refund",
                text["h_refund"],
                "refund_breakdown",
                {"by": "sku", "top_k": 3},
                "share_ge",
                operand("test", "items.0.metrics.refund_amount"),
                operand("test", "total.metrics.refund_amount"),
                "0.5",
            )
        )
    if "COST_MISSING" in warnings:
        planned.append(
            hypothesis(
                "h_ref_cost",
                text["h_cost"],
                "cost_coverage",
                {"top_k": 3},
                "share_ge",
                operand("test", "items.0.missing_cost_rows"),
                operand("test", "summary.missing_cost_rows"),
                "0.5",
            )
        )
    if any(c["code"] == "MARGIN_DROP" for _, c in triggered):
        planned.append(
            hypothesis(
                "h_ref_margin_sku",
                text["h_margin_sku"],
                "decompose_metric_change",
                {"metric": "gross_margin"},
                "share_ge",
                operand("test", "items.0.rate_effect_pp"),
                operand("test", "rate_effect_pp"),
                "0.5",
            )
        )
    if not planned:
        metrics = initial["calculate_metrics"]["evidence_id"]
        planned.append(
            hypothesis(
                "h_ref_top",
                text["h_top"],
                "rank_products",
                {"metric": "net_sales", "direction": "desc", "top_k": 3},
                "share_ge",
                operand("test", "items.0.current.metrics.net_sales"),
                operand(metrics, "current.metrics.net_sales"),
                "0.1",
            )
        )
    return planned


def first_sized(items):
    """First element with an adequate order sample (small samples cannot carry a finding)."""
    return next((i for i, item in enumerate(items) if item.get("sample") != "low"), None)


def reference_refine(text, triggered, tools, decompose):
    """One level deeper: the SKU behind the main driver."""
    codes = {c["code"] for _, c in triggered}
    refunds = ((tools.get("refund_breakdown") or {}).get("data") or {}).get("items") or []
    contributions = decompose.get("data") or {}
    rising = Decimal(str(contributions.get("total_minor") or 0)) > 0
    side = contributions.get("gainers" if rising else "decliners") or []
    index = first_sized(side)
    negative = next((c for _, c in triggered if c["code"] == "NEGATIVE_PROFIT"), None)
    if "HIGH_REFUND" in codes and refunds:
        return [
            hypothesis(
                "h_ref_sku_refund",
                text["h_sku_refund"],
                "inspect_sku",
                {"sku": refunds[0]["sku"]},
                "gt",
                operand("test", "comparison.refund_amount.delta"),
            )
        ]
    if negative and (negative.get("values") or {}).get("items"):
        return [
            hypothesis(
                "h_ref_sku_loss",
                text["h_sku_loss"],
                "inspect_sku",
                {"sku": negative["values"]["items"][0]["sku"]},
                "lt",
                operand("test", "current.metrics.gross_profit"),
            )
        ]
    if index is not None:
        return [
            hypothesis(
                "h_ref_sku_up" if rising else "h_ref_sku_down",
                text["h_sku_up" if rising else "h_sku_down"],
                "inspect_sku",
                {"sku": side[index]["sku"]},
                "gt" if rising else "lt",
                operand("test", "comparison.net_sales.change_rate"),
            )
        ]
    return []


TOPIC_OF_HYPOTHESIS = (("refund", "refund"), ("margin", "cost"), ("cost", "quality"))


def reference_turn(messages, flags):
    data = json.loads(messages[1]["content"])
    text = TEXT[data.get("language", "zh")]
    initial = by_tool(data["evidence"])
    results = tool_results(messages)
    tools = by_tool(results)
    last = messages[-1]
    if last["role"] == "user" and "Return only patches" in str(last.get("content") or ""):
        return json.dumps(patch_reply("reference", data, messages), ensure_ascii=False), []
    phase = phase_message(last)
    if phase is None and data.get("phase") == "plan" and len(messages) == 2:
        phase = {"phase": "plan"}
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
    if phase is not None and phase["phase"] == "plan":
        planned = reference_plan(data, text, triggered, warnings, initial)
        return json.dumps({"hypotheses": planned}, ensure_ascii=False), []
    if phase is not None and phase["phase"] == "refine":
        planned = reference_refine(text, triggered, tools, decompose)
        return json.dumps({"hypotheses": planned}, ensure_ascii=False), []
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
    metrics_ev = initial.get("calculate_metrics") or {}
    if has(metrics_ev.get("data") or {}, "previous", "metrics", "net_sales"):
        previous = metrics_ev["data"]["previous"]["metrics"]["net_sales"]["value"]
        if previous not in (None, "0") and not str(previous).startswith("-"):
            ev = metrics_ev["evidence_id"]
            sales_support.append(
                {
                    "template": text["times"],
                    "bindings": [
                        {
                            "name": "times",
                            "evidence_id": ev,
                            "path": "current.metrics.net_sales",
                            "format": "multiple",
                            "derive": {
                                "op": "multiple",
                                "b": {"evidence_id": ev, "path": "previous.metrics.net_sales"},
                            },
                        }
                    ],
                }
            )
    history = initial.get("get_history") or {}
    streak = ((history.get("data") or {}).get("streaks") or {}).get("net_sales") or {}
    if streak.get("periods", 0) >= 2 and streak.get("direction") in {"up", "down"}:
        sales_support.append(
            bind(
                text["streak"],
                ("periods", history["evidence_id"], "streaks.net_sales.periods", "count"),
                ("direction", history["evidence_id"], "streaks.net_sales.direction", "label"),
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
            "supporting": sales_support[:3],
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
            share = bind(text["refund_share"], ("sku", ev, "items.0.sku", "entity"))
            share["bindings"].append(
                {
                    "name": "share",
                    "evidence_id": ev,
                    "path": "items.0.metrics.refund_amount",
                    "format": "percent",
                    "derive": {
                        "op": "share",
                        "b": {"evidence_id": ev, "path": "total.metrics.refund_amount"},
                    },
                }
            )
            support.append(share)
        elif code == "SALES_CHANGE":
            side = "decliners" if decompose_data.get("decliners") else "gainers"
            position = first_sized(decompose_data.get(side) or [])
            if position is not None:
                support.append(
                    bind(
                        text["decline" if side == "decliners" else "gain"],
                        ("sku", decompose["evidence_id"], f"{side}.{position}.sku", "entity"),
                        (
                            "amount",
                            decompose["evidence_id"],
                            f"{side}.{position}.sales_contribution_minor",
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
            split = tools.get("decompose_metric_change") or {}
            items = (split.get("data") or {}).get("items") or []
            if items and items[0].get("sku") and items[0].get("sample") != "low":
                support.append(
                    bind(
                        text["margin_sku"],
                        ("sku", split["evidence_id"], "items.0.sku", "entity"),
                        ("pp", split["evidence_id"], "items.0.rate_effect_pp", "pp"),
                    )
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
        change = None
        if has(drill_data, "comparison", "net_sales", "change_rate"):
            change = bind(
                text["drill_change"],
                ("sku", ev, "sku", "entity"),
                ("change", ev, "comparison.net_sales.change_rate", "percent"),
            )
        target = findings[1] if len(findings) > 1 else findings[0]
        if change and drill_data.get("sample") == "low":
            # A small-sample change cannot carry a supporting sentence; keep it as a hypothesis.
            target["hypotheses"] = (target["hypotheses"] + [change])[:3]
        elif change:
            support.append(change)
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
    # Cite a note only next to a product it names that actually drives the change.
    drivers = [
        (decompose["evidence_id"], f"{key}.{i}.sku", item["sku"])
        for key in ("gainers", "decliners")
        for i, item in enumerate((decompose_data.get(key) or [])[:2])
    ]
    if refund_items:
        drivers.append(
            (tools["refund_breakdown"]["evidence_id"], "items.0.sku", refund_items[0]["sku"])
        )
    for j, note in enumerate(note_items):
        named = next((d for d in drivers if d[2] and d[2] in note.get("text", "")), None)
        if named:
            findings[0]["hypotheses"].append(
                bind(
                    text["note"],
                    ("sku", named[0], named[1], "entity"),
                    ("kind", notes["evidence_id"], f"items.{j}.kind", "label"),
                    ("note", notes["evidence_id"], f"items.{j}.text", "note"),
                )
            )
            break
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
    follow = initial.get("check_recommendation") or {}
    follow_items = ((follow.get("data") or {}).get("items") or [])[:4]
    if follow_items:
        ev = follow["evidence_id"]
        sentences = []
        for i, item in enumerate(follow_items):
            parts = [
                ("action", ev, f"items.{i}.action_text", "note"),
                ("state", ev, f"items.{i}.state", "label"),
            ]
            if item.get("change_rate") is None:
                sentences.append(bind(text["followup"], *parts))
                continue
            sentences.append(
                bind(
                    text["followup_change"],
                    *parts,
                    ("metric", ev, f"items.{i}.verification_metric", "label"),
                    ("change", ev, f"items.{i}.change_rate", "percent"),
                )
            )
        # Every earlier recommendation gets its verdict, so this finding survives truncation and
        # takes no new recommendation of its own.
        findings = findings[:4] + [
            {
                "id": "f_followup",
                "topic": "followup",
                "title": text["followup_title"],
                "observation": sentences[0],
                "supporting": sentences[1:],
                "hypotheses": [],
            }
        ]
    # The policy's own deeper hypotheses first: they name the products behind a change.
    tested = sorted(verdicts(messages), key=lambda v: -v.get("wave", 0))
    for finding in findings:
        finding.setdefault("hypothesis_ids", [])
    for verdict in tested:
        if verdict["state"] != "supported":
            continue
        topic = next((t for key, t in TOPIC_OF_HYPOTHESIS if key in verdict["id"]), "sales")
        finding = next((f for f in findings if f["topic"] == topic), findings[0])
        if len(finding["hypothesis_ids"]) < 3 and verdict["id"] not in finding["hypothesis_ids"]:
            finding["hypothesis_ids"].append(verdict["id"])
    ruled_out = [
        {
            "hypothesis_id": verdict["id"],
            "sentence": bind(
                text["ruled_out"], ("state", verdict["evidence_id"], "state", "label")
            ),
        }
        for verdict in tested
        if verdict["state"] == "refuted"
    ][:3]
    if data["kind"] == "report":
        final = {
            "summary": facts[:2],
            "findings": findings[:5],
            "recommendations": recommendations[:4],
            "ruled_out": ruled_out,
        }
    else:
        supporting = [s for f in findings for s in f["supporting"]]
        # Prefer sentences that name a product: they answer "which one" questions directly.
        supporting.sort(key=lambda s: not any(b["format"] == "entity" for b in s["bindings"]))
        supporting = [
            s for s in supporting if not any(b.get("derive") for b in s["bindings"])
        ] or supporting
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
