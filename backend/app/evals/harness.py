"""Run evaluation cases through the real tools, workflow and validator; score the results."""

import re
import uuid
from decimal import Decimal

from app.evals.synthetic import generate
from app.metrics.engine import calculate
from app.reports.drill import drill_payload
from app.reports.grammar import walk
from app.reports.schema import GRAMMAR_VERSION, PROMPT_VERSION, Rules
from app.reports.tools import ToolError, ToolRegistry
from app.reports.workflow import ReportWorkflow

# Higher is better unless listed in LOWER_IS_BETTER. Gated metrics fail CI when they regress.
GATED = (
    "success",
    "first_pass",
    "entity_coverage",
    "rule_recall",
    "rule_mention",
    "tool_effectiveness",
)
LOWER_IS_BETTER = ("forbidden_hits",)


def _value(product, key):
    value = product["current"]["metrics"][key]["value"]
    return Decimal(value) if value is not None else None


def build_context(case):
    data = generate(case["data"])
    output = calculate(data["rows"], data["snapshot"], data["query"])
    result, products = output["result"], output["products"]
    rankings = {}
    for metric in ("net_sales", "gross_profit", "refund_amount", "paid_units"):
        for direction in ("asc", "desc"):
            present = [p for p in products if _value(p, metric) is not None]
            absent = [p for p in products if _value(p, metric) is None]
            sign = -1 if direction == "desc" else 1
            # Same order as the SQL ranking: value (nulls last), then group_key ascending.
            present.sort(key=lambda p, m=metric, s=sign: (s * _value(p, m), p["group_key"]))
            rankings[f"{metric}:{direction}"] = (present + absent)[:50]
    rankings["confirmed_negative_profit"] = sorted(
        [
            p
            for p in products
            if p["current"]["metrics"]["gross_profit"]["quality"] == "confirmed"
            and (_value(p, "gross_profit") or 0) < 0
        ],
        key=lambda p: (_value(p, "gross_profit"), p["group_key"]),
    )[:50]
    missing = [p for p in products if p["current"]["quality"]["missing_cost_rows"] > 0]
    missing.sort(key=lambda p: (-(_value(p, "net_sales") or 0), p["group_key"]))
    notes = [
        {"id": str(uuid.UUID(int=i + 1)), **note} for i, note in enumerate(case.get("notes", []))
    ]
    context = {
        "result": result,
        "rankings": rankings,
        "rules": Rules().model_dump(),
        "language": case.get("language", "zh"),
        "missing_cost": missing[:20],
        "followups": [],
        "notes": notes,
        "stats": {
            "active_skus": sum(
                1 for p in products if (_value(p, "paid_units") or 0) > 0 and p["sku"] is not None
            ),
            "negative_sales": sum(1 for p in products if (_value(p, "net_sales") or 0) < 0),
            "unmapped": sum(1 for p in products if p["sku"] is None),
        },
    }

    def drill(sku):
        rows = [r for r in data["rows"] if r["sku"] == sku]
        if not rows:
            raise ToolError("SKU_NOT_FOUND")
        return drill_payload(sku, rows, data["snapshot"], result["query"])

    return context, drill


def texts_of(analysis):
    if not analysis:
        return []
    texts = [s["text"] for s in analysis.get("summary") or []]
    for finding in analysis.get("findings") or []:
        texts += [finding["title"], finding["observation"]["text"]]
        texts += [s["text"] for s in finding.get("supporting") or []]
        texts += list(finding.get("hypotheses") or [])
    texts += [r["action"] for r in analysis.get("recommendations") or []]
    if analysis.get("clarify"):
        texts.append(analysis["clarify"]["text"])
    return texts


def bindings_of(raw):
    found = []

    def visit(value):
        if isinstance(value, dict):
            if isinstance(value.get("bindings"), list) and "template" in value:
                found.extend(b for b in value["bindings"] if isinstance(b, dict))
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(raw)
    return found


def score(case, output, evidence):
    expect = case.get("expect", {})
    analysis = output["analysis"]
    texts = texts_of(analysis)
    joined = "\n".join(texts)
    by_id = {e["evidence_id"]: e for e in evidence}
    detect = next(e for e in evidence if e["tool"] == "detect_anomalies")
    triggered = {c["code"] for c in detect["payload"]["checks"] if c["state"] == "triggered"}
    expected_rules = set(expect.get("rules", []))
    bindings = bindings_of(output.get("raw_analysis"))
    mentioned_rules = set()
    for b in bindings:
        ev = by_id.get(b.get("evidence_id"))
        if (
            ev
            and ev["tool"] == "detect_anomalies"
            and re.fullmatch(r"checks\.\d+\.code", b["path"])
        ):
            try:
                mentioned_rules.add(walk(ev["payload"], b["path"]))
            except (KeyError, TypeError):
                pass
    entities = expect.get("entities", [])
    entities_any = expect.get("entities_any", [])
    if entities:
        entity_coverage = sum(1 for e in entities if e in joined) / len(entities)
    elif entities_any:
        entity_coverage = 1.0 if any(e in joined for e in entities_any) else 0.0
    else:
        entity_coverage = 1.0
    extra_ids = {e["evidence_id"] for e in output.get("extra_evidence") or []}
    referenced = {b.get("evidence_id") for b in bindings} & extra_ids
    ok_calls = [s for s in output["steps"] if s.get("phase") == "tool" and s.get("ok")]
    forbidden = sum(len(re.findall(p, joined, re.I)) for p in expect.get("forbidden", []))
    if expect.get("note") and analysis:
        note_mentioned = any(b.get("format") == "note" for b in bindings)
    else:
        note_mentioned = None
    success = analysis is not None
    return {
        "id": case["id"],
        "success": float(success),
        "first_pass": float(success and output.get("repairs", 0) == 0),
        "repairs": output.get("repairs", 0),
        "error_code": output.get("error_code"),
        "requests": output["usage"].get("requests", 0),
        "tool_calls": output["usage"].get("tools", 0),
        "tool_rounds": output["usage"].get("tool_rounds", 0),
        "tool_effectiveness": len(referenced) / len(ok_calls) if ok_calls else None,
        "entity_coverage": entity_coverage if success else 0.0,
        "rule_recall": len(expected_rules & triggered) / len(expected_rules)
        if expected_rules
        else 1.0,
        "rule_mention": len(expected_rules & mentioned_rules) / len(expected_rules)
        if expected_rules and success
        else (1.0 if success else 0.0),
        "triggered_rules": sorted(triggered),
        "forbidden_hits": forbidden,
        "note_mentioned": note_mentioned,
        "texts": texts,
        "steps": [
            {k: s.get(k) for k in ("phase", "tool", "ok", "code", "reason", "codes") if k in s}
            for s in output["steps"]
        ],
    }


def run_case(case, transport, config, key=""):
    context, drill = build_context(case)
    report_id, run_id = str(uuid.uuid4()), str(uuid.uuid4())
    registry = ToolRegistry(context, report_id, run_id)
    registry.core()
    result = context["result"]
    kind = case.get("kind", "report")
    request = {
        "config": config,
        "key": key,
        "context": context,
        "evidence": list(registry.evidence),
        "report_id": report_id,
        "run_id": run_id,
        "kind": kind,
        "intent": case.get("intent", "business_review"),
        "language": case.get("language", "zh"),
        "dataset_id": result["dataset_id"],
        "currency": result["currency"],
        "currency_exponent": result["currency_exponent"],
        "scope": result["query"],
        "question": case.get("question"),
        "prompt_version": PROMPT_VERSION,
    }
    output = ReportWorkflow(request, transport, drill=drill).run()
    evidence = registry.evidence + (output.get("extra_evidence") or [])
    return score(case, output, evidence)


def aggregate(results):
    def mean(key):
        values = [r[key] for r in results if r.get(key) is not None]
        return round(sum(values) / len(values), 4) if values else None

    summary = {key: mean(key) for key in GATED}
    summary.update(
        repair_rate=round(sum(1 for r in results if r["repairs"]) / len(results), 4),
        requests=mean("requests"),
        tool_calls=mean("tool_calls"),
        forbidden_hits=sum(r["forbidden_hits"] for r in results),
        note_mention=mean("note_mentioned"),
        cases=len(results),
    )
    for key in ("plausibility", "actionability", "grounding"):
        values = [r["judge"][key] for r in results if r.get("judge") and r["judge"].get(key)]
        if values:
            summary["judge_" + key] = round(sum(values) / len(values), 3)
    return summary


def gate(current, baseline, tolerance=0.05):
    """Return a list of regressions of the current aggregate against the baseline."""
    failures = []
    for key in GATED:
        before, after = baseline.get(key), current.get(key)
        if before is not None and after is not None and after < before - tolerance:
            failures.append(f"{key}: {after} < baseline {before} - {tolerance}")
    for key in LOWER_IS_BETTER:
        if current.get(key, 0) > baseline.get(key, 0):
            failures.append(f"{key}: {current.get(key)} > baseline {baseline.get(key)}")
    return failures


def versions():
    return {"prompt_version": PROMPT_VERSION, "grammar_version": GRAMMAR_VERSION}
