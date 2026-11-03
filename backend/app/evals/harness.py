"""Run evaluation cases through the real tools, workflow and validator; score the results.

Two kinds of answer keys:

- Deterministic keys (``pipeline_*``): the server's own judgements of its candidate hypotheses,
  decomposition dominance, history streaks, small-sample flags, period-to-period rechecks and
  question routing. They do not depend on the model, so the offline suite gates them exactly.
- Model keys: injected causes the report should identify through cited supported hypotheses,
  distractors it must not cite, plus behaviour metrics (hypothesis validity, deepening, causal
  overclaiming, repairs, review, latency, tokens). They are what the live suite measures.

Cases marked ``live_only`` need a judgement the scripted reference policy cannot make (asking
back on an ambiguous question); the offline suite skips them.
"""

import math
import re
import uuid
from collections import Counter
from decimal import Decimal
from types import SimpleNamespace

from app.evals.judge import DIMENSIONS as JUDGE_DIMENSIONS
from app.evals.synthetic import generate
from app.metrics.engine import calculate, history
from app.reports.drill import drill_payload
from app.reports.grammar import walk
from app.reports.hypothesis import seed
from app.reports.schema import GRAMMAR_VERSION, PROMPT_VERSION, Rules
from app.reports.tools import ToolError, ToolRegistry, history_payload
from app.reports.workflow import ReportWorkflow

# Higher is better unless listed in LOWER_IS_BETTER. Gated metrics fail CI when they regress.
GATED = (
    "success",
    "first_pass",
    "entity_coverage",
    "rule_recall",
    "rule_mention",
    "tool_effectiveness",
    "hypothesis_cited",
    "pipeline_accuracy",
    "cause_recall",
)
LOWER_IS_BETTER = ("forbidden_hits", "lint_issues", "distractor_misuse", "overclaim_rate")
# Averaged in the aggregate (None values skipped) next to the gated metrics.
MEANS = (
    "requests",
    "tool_calls",
    "hypothesis_tests",
    "hypothesis_validity",
    "ruled_out_listed",
    "deepened",
    "sku_drill",
    "derived_bindings",
    "repairs_patch",
    "repairs_full",
    "patch_success",
    "review_applied",
    "latency_ms",
    "input_tokens",
    "output_tokens",
    "cached_tokens",
    "followup_mention",
    "kind_match",
)
PIPELINE_GROUPS = ("verdict", "dominance", "streak", "low_sample", "recheck", "intent", "followup")
CAUSAL = re.compile(
    r"导致|造成|由于|因为|致使|归因于|"
    r"\b(?:caused|causes|causing|because|due to|led to|leads to|results? in|resulted in)\b",
    re.I,
)
# A sentence that names the data it lacks ("当前没有流量和广告数据") is a disclosed gap, not a
# claim; forbidden terms in it are not counted.
DATA_GAP = re.compile(
    r"(?:没有|无|缺少|缺乏|未提供)[^。；;\n]{0,16}数据|"
    r"\b(?:no|without|lack of|missing)\b[^.;\n]{0,40}\bdata\b"
    r"|\bdata\b[^.;\n]{0,20}\bnot (?:available|provided)\b",
    re.I,
)


def _value(product, key):
    value = product["current"]["metrics"][key]["value"]
    return Decimal(value) if value is not None else None


def history_windows(query):
    from app.reports.service import history_windows as windows

    return windows(query)


def followups_of(case, data, result):
    """Earlier action items from the previous period, judged by the report service's own rule."""
    from app.reports.followups import evaluate

    items = []
    for i, spec in enumerate(case.get("followups") or []):
        query = {
            **data["query"],
            "start": result["query"]["compare_start"],
            "end_exclusive": result["query"]["compare_end_exclusive"],
            "skus": spec.get("skus", data["query"]["skus"]),
        }
        earlier = calculate(data["rows"], data["snapshot"], query)["result"]
        item = SimpleNamespace(
            id=uuid.UUID(int=1001 + i),
            text=spec["action"],
            verification_metric=spec["verification_metric"],
            priority=spec.get("priority", "high"),
            status="open",
        )
        source = SimpleNamespace(
            id=uuid.UUID(int=2001 + i), content={"metrics": earlier}, query=earlier["query"]
        )
        items.append(evaluate(item, source, result))
    return items


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
        "followups": followups_of(case, data, result),
        "notes": notes,
        "stats": {
            "active_skus": sum(
                1 for p in products if (_value(p, "paid_units") or 0) > 0 and p["sku"] is not None
            ),
            "negative_sales": sum(1 for p in products if (_value(p, "net_sales") or 0) < 0),
            "unmapped": sum(1 for p in products if p["sku"] is None),
        },
    }

    windows, days = history_windows(result["query"])
    if windows:
        raw = history(data["rows"], data["snapshot"], windows)
        if any(w["coverage_complete"] for w in raw["windows"]):
            context["history"] = history_payload(raw, result, days)

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


def sections_of(analysis):
    """Rendered report text by section: all the LLM judge sees besides the case description."""
    if not analysis:
        return {}
    return {
        "summary": [s["text"] for s in analysis.get("summary") or []],
        "findings": [
            {
                "title": f["title"],
                "observation": f["observation"]["text"],
                "supporting": [s["text"] for s in f.get("supporting") or []],
                "hypotheses": list(f.get("hypotheses") or []),
                "supported_hypotheses": [
                    h.get("text") or "" for h in f.get("supported_hypotheses") or []
                ],
            }
            for f in analysis.get("findings") or []
        ],
        "ruled_out": [
            {"hypothesis": r["statement"], "result": r["text"]}
            for r in analysis.get("ruled_out") or []
        ],
        "recommendations": [r["action"] for r in analysis.get("recommendations") or []],
        "clarify": (analysis.get("clarify") or {}).get("text"),
    }


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


def dominant(decomposition, metric):
    if not decomposition or not decomposition.get("available"):
        return None
    if metric == "aov":
        price, basket = (
            abs(Decimal(decomposition[k])) for k in ("price_effect_minor", "basket_effect_minor")
        )
        return "price" if price > basket else "basket"
    mix, rate = (abs(Decimal(decomposition[k])) for k in ("mix_effect_pp", "rate_effect_pp"))
    return "mix" if mix > rate else "rate"


def recheck_states(case, registry):
    """Re-judge this case's hypotheses on the follow-up period in ``expect.recheck.next``."""
    from app.reports.service import hypothesis_items

    prior = [
        {
            "id": h["id"],
            "statement": h["statement"],
            "previous_state": h["state"],
            "source_report_id": registry.report_id,
            "spec": h["spec"],
        }
        for h in hypothesis_items(registry.evidence)
        if h["state"] in {"supported", "refuted"}
    ][:5]
    follow = {**case, "data": case["expect"]["recheck"]["next"], "notes": []}
    context, drill = build_context(follow)
    later = ToolRegistry(context, str(uuid.uuid4()), str(uuid.uuid4()), drill=drill)
    _, rechecked = seed(later, later.core(), case.get("language", "zh"), prior)
    return {i["id"]: i["state"] for i in (rechecked["payload"]["items"] if rechecked else [])}


def pipeline_checks(case, context, drill, registry, intent=None):
    """Deterministic answer keys: {"group:key": bool}."""
    expect = case.get("expect", {})
    checks = {}
    states = {
        e["payload"]["id"]: e["payload"]["state"]
        for e in registry.evidence
        if e["tool"] == "test_hypothesis" and e["payload"]["wave"] == 0
    }
    for hypothesis_id, state in expect.get("verdicts", {}).items():
        checks["verdict:" + hypothesis_id] = states.get(hypothesis_id) == state
    decompositions = context["result"].get("decompositions") or {}
    for metric, expected in expect.get("dominance", {}).items():
        checks["dominance:" + metric] = dominant(decompositions.get(metric), metric) == expected
    streaks = (context.get("history") or {}).get("streaks") or {}
    for metric, spec in expect.get("streaks", {}).items():
        found = streaks.get(metric) or {}
        checks["streak:" + metric] = (
            found.get("direction") == spec["direction"]
            and found.get("periods", 0) >= spec["min_periods"]
        )
    if expect.get("low_sample"):
        fresh = ToolRegistry(context, registry.report_id, registry.run_id, drill=drill)
        ranked = fresh.execute(
            "rank_products", {"metric": "net_sales", "direction": "asc", "top_k": 50}, core=True
        )
        low = {p["sku"] for p in ranked["payload"]["items"] if p["sample"] == "low"}
        for sku in expect["low_sample"]:
            checks["low_sample:" + sku] = sku in low
    if expect.get("recheck"):
        rechecked = recheck_states(case, registry)
        for hypothesis_id, state in expect["recheck"]["states"].items():
            checks["recheck:" + hypothesis_id] = rechecked.get(hypothesis_id) == state
    if expect.get("intent"):
        checks["intent:" + expect["intent"]] = intent == expect["intent"]
    if expect.get("followups"):
        found = next((e for e in registry.evidence if e["tool"] == "check_recommendation"), None)
        states = [i["state"] for i in found["payload"]["items"]] if found else []
        for i, state in enumerate(expect["followups"]):
            checks[f"followup:{i}"] = i < len(states) and states[i] == state
    return checks


def pipeline_scores(checks):
    def rate(values):
        return round(sum(values) / len(values), 4) if values else None

    scores = {
        f"pipeline_{group}": rate([v for k, v in checks.items() if k.split(":")[0] == group])
        for group in PIPELINE_GROUPS
    }
    scores["pipeline_accuracy"] = rate(list(checks.values()))
    scores["pipeline_failures"] = sorted(k for k, v in checks.items() if not v)
    return scores


def verdict_skus(payload):
    skus = {payload["test"]["arguments"].get("sku")}
    for operand in payload.get("operands") or []:
        select = operand.get("select") or {}
        if select.get("key") == "sku":
            skus.add(select.get("value"))
    return {s for s in skus if s}


def matches(matcher, cited, ruled_ids, note_texts):
    """Does the report satisfy one matcher of a cause or distractor?"""
    if "ruled_out" in matcher:
        return matcher["ruled_out"] in ruled_ids
    if "note" in matcher:
        return any(matcher["note"] in text for text in note_texts)
    for payload in cited:
        if "hypothesis" in matcher and payload["id"] != matcher["hypothesis"]:
            continue
        if "sku" in matcher and matcher["sku"] not in verdict_skus(payload):
            continue
        if "tool" in matcher and payload["test"]["tool"] != matcher["tool"]:
            continue
        if "metric" in matcher and payload["test"]["arguments"].get("metric") != matcher["metric"]:
            continue
        return True
    return False


def model_metrics(case, output, evidence, bindings):
    """Behaviour of the model on top of the deterministic pipeline."""
    expect = case.get("expect", {})
    analysis = output["analysis"] or {}
    steps = output["steps"]
    verdicts = {
        e["payload"]["id"]: e["payload"] for e in evidence if e["tool"] == "test_hypothesis"
    }
    findings = analysis.get("findings") or []
    cited = [
        verdicts[item["id"]]
        for finding in findings
        for item in finding.get("supported_hypotheses") or []
        if item["id"] in verdicts
    ]
    ruled_ids = {item["hypothesis_id"] for item in analysis.get("ruled_out") or []}
    by_id = {e["evidence_id"]: e for e in evidence}
    note_texts = []
    for binding in bindings:
        ev = by_id.get(binding.get("evidence_id"))
        if ev and binding.get("format") == "note":
            try:
                note_texts.append(str(walk(ev["payload"], binding["path"])))
            except (KeyError, TypeError):
                pass
    success = output["analysis"] is not None
    causes = expect.get("causes") or []
    found = [any(matches(m, cited, ruled_ids, note_texts) for m in cause) for cause in causes]
    distractors = expect.get("distractors") or []
    tests = [s for s in steps if s.get("phase") == "test"]
    waves = [s for s in steps if s.get("phase") == "hypotheses"]
    hypothesis_mode = output.get("mode") == "hypotheses"
    claimed = [f for f in findings if f.get("supported_hypotheses")]
    overclaims = 0
    for finding in claimed:
        texts = [finding["observation"]["text"], *[s["text"] for s in finding["supporting"]]]
        texts += [h["text"] or "" for h in finding["supported_hypotheses"]]
        overclaims += bool(CAUSAL.search("\n".join(texts)))
    repairs = [s for s in steps if s.get("phase") == "repair"]
    patches = [s for s in repairs if s.get("mode") == "patch"]
    models = [s for s in steps if s.get("phase") == "model" and "error" not in s]
    review = next((s for s in steps if s.get("phase") == "review_repair"), None)
    return {
        "cause_recall": (sum(found) / len(causes) if success else 0.0) if causes else None,
        "causes_found": found,
        "distractor_misuse": sum(
            1 for m in distractors if matches(m, cited, ruled_ids, note_texts)
        ),
        "hypothesis_validity": sum(1 for s in tests if s.get("ok")) / len(tests) if tests else None,
        "test_errors": sorted(s["code"] for s in tests if not s.get("ok") and s.get("code")),
        "deepened": float(any(w.get("wave") == 2 for w in waves)) if hypothesis_mode else None,
        "sku_drill": float(
            any(s.get("tool") == "inspect_sku" for s in tests)
            or any(verdict_skus(v) for v in verdicts.values() if v["wave"] >= 1)
        )
        if hypothesis_mode
        else None,
        "overclaim_rate": overclaims / len(claimed) if claimed else None,
        "derive_errors": sum(
            1 for s in repairs for code in s.get("codes") or [] if code.startswith("DERIVE_")
        ),
        "repairs_patch": len(patches),
        "repairs_full": len(repairs) - len(patches),
        "patch_success": float(success) if patches else None,
        "review_applied": float(review["applied"]) if review else None,
        "latency_ms": sum(s.get("latency_ms") or 0 for s in models),
        "input_tokens": sum(s.get("input_tokens") or 0 for s in models),
        "output_tokens": sum(s.get("output_tokens") or 0 for s in models),
        "cached_tokens": sum(s.get("cached_tokens") or 0 for s in models),
        "cited_hypotheses": sorted({v["id"] for v in cited}),
        "ruled_out": sorted(ruled_ids),
        "verdicts": {k: v["state"] for k, v in sorted(verdicts.items())},
    }


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
    cited = set()
    for finding in (analysis or {}).get("findings") or []:
        for item in finding.get("supported_hypotheses") or []:
            cited |= {item["evidence_id"], item["test_evidence_id"]}
    for item in (analysis or {}).get("ruled_out") or []:
        cited |= set(item["evidence_refs"])
    referenced = {b.get("evidence_id") for b in bindings} | cited
    ok_calls = [s for s in output["steps"] if s.get("phase") in {"tool", "test"} and s.get("ok")]
    effective = [
        s for s in ok_calls if {s.get("evidence_id"), s.get("test_evidence_id")} & referenced
    ]
    tested = [e["payload"] for e in evidence if e["tool"] == "test_hypothesis"]
    supported = {v["id"] for v in tested if v["state"] == "supported"}
    refuted = {v["id"] for v in tested if v["state"] == "refuted"}
    cited_ids = {
        item["id"]
        for finding in (analysis or {}).get("findings") or []
        for item in finding.get("supported_hypotheses") or []
    }
    ruled_ids = {item["hypothesis_id"] for item in (analysis or {}).get("ruled_out") or []}
    # The lint event, not a review-model error event that shares its phase.
    review = next((s for s in output["steps"] if s.get("phase") == "review" and "lint" in s), {})
    lint_codes = review.get("lint") or []
    forbidden = sum(
        len(re.findall(p, text, re.I))
        for text in texts
        if not DATA_GAP.search(text)
        for p in expect.get("forbidden", [])
    )
    if expect.get("note") and analysis:
        note_mentioned = any(b.get("format") == "note" for b in bindings)
    else:
        note_mentioned = None
    followup = next((e for e in evidence if e["tool"] == "check_recommendation"), None)
    followup_mention = None
    if followup and followup["payload"]["items"] and analysis:
        stated = {
            b["path"]
            for b in bindings
            if b.get("evidence_id") == followup["evidence_id"]
            and re.fullmatch(r"items\.\d+\.state", b.get("path", ""))
        }
        followup_mention = len(stated) / len(followup["payload"]["items"])
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
        "tool_effectiveness": len(effective) / len(ok_calls) if ok_calls else None,
        "hypothesis_tests": sum(1 for s in output["steps"] if s.get("phase") == "test"),
        "hypothesis_cited": len(cited_ids & supported) / len(supported)
        if supported and success
        else None,
        "ruled_out_listed": len(ruled_ids & refuted) / len(refuted)
        if refuted and success
        else None,
        "derived_bindings": sum(1 for b in bindings if b.get("derive")),
        "lint_issues": len(lint_codes),
        "direction_flags": lint_codes.count("DIRECTION_MISMATCH"),
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
        "followup_mention": followup_mention,
        "kind_match": float(bool(analysis) and analysis.get("kind") == expect["kind"])
        if expect.get("kind")
        else None,
        **model_metrics(case, output, evidence, bindings),
        "texts": texts,
        "report": sections_of(analysis),
        "steps": [
            {
                k: s.get(k)
                for k in ("phase", "tool", "ok", "code", "reason", "codes", "id", "state", "mode")
                if k in s
            }
            for s in output["steps"]
        ],
    }


def routed(case, intent, checks):
    """A question answered by server routing alone (missing data, other scope): no model call."""
    ok = checks.get("intent:" + case["expect"].get("intent", "")) is not False
    return {
        "id": case["id"],
        "routed": intent,
        "success": float(ok),
        "first_pass": float(ok),
        "repairs": 0,
        "error_code": None if ok else "ROUTING_MISMATCH",
        "requests": 0,
        "tool_calls": 0,
        "entity_coverage": float(ok),
        "rule_recall": 1.0,
        "rule_mention": float(ok),
        "triggered_rules": [],
        "forbidden_hits": 0,
        "lint_issues": 0,
        "direction_flags": 0,
        "distractor_misuse": 0,
        "texts": [],
        "steps": [],
        **pipeline_scores(checks),
    }


def run_case(case, transport, config, key=""):
    from app.reports.service import question_intent

    context, drill = build_context(case)
    report_id, run_id = str(uuid.uuid4()), str(uuid.uuid4())
    registry = ToolRegistry(context, report_id, run_id)
    seed(registry, registry.core(), case.get("language", "zh"))
    result = context["result"]
    kind = case.get("kind", "report")
    intent = case.get("intent", "business_review")
    if kind == "question":
        intent = question_intent(case["question"], result["query"])
    checks = pipeline_checks(case, context, drill, registry, intent)
    if intent in {"missing_data", "out_of_scope"}:
        return routed(case, intent, checks)
    request = {
        "config": config,
        "key": key,
        "context": context,
        "evidence": list(registry.evidence),
        "report_id": report_id,
        "run_id": run_id,
        "kind": kind,
        "intent": intent,
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
    return {**score(case, output, evidence), **pipeline_scores(checks)}


def runnable(cases, suite):
    """(cases to run, live-only cases skipped): the offline suite cannot score those."""
    if suite == "live":
        return cases, []
    return [c for c in cases if not c.get("live_only")], [c for c in cases if c.get("live_only")]


def percentile(values, q):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(q * len(ordered)) - 1))]


def aggregate(results):
    def mean(key):
        values = [r[key] for r in results if r.get(key) is not None]
        return round(sum(values) / len(values), 4) if values else None

    modelled = [r for r in results if not r.get("routed")]
    latencies = [r["latency_ms"] for r in modelled if r.get("latency_ms")]
    tokens = sum(r.get("input_tokens") or 0 for r in modelled)
    summary = {key: mean(key) for key in GATED}
    summary.update({key: mean(key) for key in MEANS})
    summary.update({f"pipeline_{group}": mean(f"pipeline_{group}") for group in PIPELINE_GROUPS})
    summary.update(
        repair_rate=round(sum(1 for r in results if r["repairs"]) / len(results), 4),
        lint_issues=sum(r["lint_issues"] for r in results),
        direction_flags=sum(r.get("direction_flags") or 0 for r in results),
        forbidden_hits=sum(r["forbidden_hits"] for r in results),
        distractor_misuse=sum(r.get("distractor_misuse") or 0 for r in results),
        overclaim_rate=mean("overclaim_rate") or 0,
        derive_errors=sum(r.get("derive_errors") or 0 for r in results),
        latency_p50_ms=percentile(latencies, 0.5),
        latency_p90_ms=percentile(latencies, 0.9),
        cache_ratio=round(sum(r.get("cached_tokens") or 0 for r in modelled) / tokens, 4)
        if tokens
        else None,
        test_errors=dict(Counter(code for r in results for code in r.get("test_errors") or [])),
        pipeline_failures=sorted(
            f"{r['id']}:{failure}" for r in results for failure in r.get("pipeline_failures") or []
        ),
        note_mention=mean("note_mentioned"),
        cases=len(results),
    )
    # Only an LLM judge produces judge_* values; offline runs report pipeline metrics alone.
    for key in JUDGE_DIMENSIONS:
        values = [r["judge"][key] for r in results if r.get("judge") and r["judge"].get(key)]
        if values:
            summary["judge_" + key] = round(sum(values) / len(values), 3)
    return summary


def spread(results, repeats):
    """Mean, standard deviation and range of each numeric aggregate across repeated runs."""
    if repeats < 2:
        return None
    runs = [aggregate([r for r in results if r.get("repeat") == i]) for i in range(repeats)]
    found = {}
    for key, value in runs[0].items():
        if isinstance(value, bool) or not isinstance(value, int | float):
            continue
        values = [run[key] for run in runs if isinstance(run.get(key), int | float)]
        if len(values) < 2:
            continue
        mean = sum(values) / len(values)
        deviation = math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1))
        found[key] = {
            "mean": round(mean, 4),
            "stdev": round(deviation, 4),
            "min": min(values),
            "max": max(values),
        }
    return found


def gate(current, baseline, tolerance=0.05):
    """Return a list of regressions of the current aggregate against the baseline."""
    failures = []
    for key in GATED:
        before, after = baseline.get(key), current.get(key)
        if before is not None and after is not None and after < before - tolerance:
            failures.append(f"{key}: {after} < baseline {before} - {tolerance}")
    for key in LOWER_IS_BETTER:
        if (current.get(key) or 0) > (baseline.get(key) or 0):
            failures.append(f"{key}: {current.get(key)} > baseline {baseline.get(key)}")
    if current.get("pipeline_failures"):
        # Deterministic answer keys never tolerate a miss, whatever the baseline says.
        failures.append("pipeline: " + ", ".join(current["pipeline_failures"]))
    return failures


def versions():
    return {"prompt_version": PROMPT_VERSION, "grammar_version": GRAMMAR_VERSION}
