"""Hypothesis tests decided by the server.

A hypothesis names a test (one read-only tool call) and a machine-checkable expectation over
values of the resulting evidence. The server runs the test, evaluates the expectation and records
``supported``, ``refuted`` or ``inconclusive``; the model never labels its own hypotheses.
"supported" only means the data is consistent with the statement, never that a cause is proven.

Expectations reference values by path inside the test evidence ("test") or another evidence
record. ``select`` picks list elements by key (SKU, date, rule code) because positions change
between runs; after evaluation every positional reference is anchored to a key, so the stored
spec can be re-run on the next report of the same series (``recheck``).
"""

from decimal import Decimal, localcontext

from app.reports.derive import DeriveError, compute, number_text, operand, public
from app.reports.grammar import rule_for
from app.reports.schema import SELECT_KEYS, SELECT_LISTS

STATES = ("supported", "refuted", "inconclusive")
TEST_TOOLS_EXCLUDED = {"derive", "explain_metric"}
INVALID = {
    "PATH_NOT_ALLOWED",
    "NOT_A_NUMBER",
    "PATH_NOT_FOUND",
    "UNIT_MISMATCH",
    "METRIC_MISMATCH",
    "NOT_A_TOTAL",
    "PERIOD_MISMATCH",
    "UNKNOWN_OP",
}


class HypothesisError(ValueError):
    """The hypothesis itself is malformed (not a data outcome)."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


class Outcome(Exception):
    """Short-circuit with a decided state."""

    def __init__(self, state, reason=None):
        self.state, self.reason = state, reason
        super().__init__(state)


def arguments(raw):
    return {k: v for k, v in (raw or {}).items() if v is not None}


def locate(ev, spec):
    """Positional path and list index for an operand (``select`` resolved)."""
    select, path = spec.get("select"), spec.get("path") or ""
    if not select:
        return path, None
    items = ev["payload"].get(select["list"]) if isinstance(ev["payload"], dict) else None
    if not isinstance(items, list):
        raise HypothesisError("SELECT_LIST_MISSING")
    for index, item in enumerate(items):
        if isinstance(item, dict) and str(item.get(select["key"])) == select["value"]:
            return f"{select['list']}.{index}" + (f".{path}" if path else ""), index
    raise Outcome("refuted" if spec.get("_rank") else "inconclusive", "NOT_FOUND")


LARGE = {"gt", "abs_ge", "abs_gt", "share_ge"}


def complete(ev, spec):
    """True when the selected list was not cut by ``top_k`` (it lists every nonzero element)."""
    items = ev["payload"].get(spec["select"]["list"]) or []
    top_k = (ev.get("args") or {}).get("top_k")
    return ev["tool"] in {"refund_breakdown", "cost_coverage"} and top_k and len(items) < top_k


def anchor(ev, path):
    """Turn ``items.3.metrics.x`` into a key-based select when the element has a key."""
    parts = path.split(".")
    if len(parts) >= 2 and parts[0] in SELECT_LISTS and parts[1].isdigit():
        items = ev["payload"].get(parts[0])
        item = items[int(parts[1])] if isinstance(items, list) else None
        if isinstance(item, dict):
            for key in SELECT_KEYS:
                if isinstance(item.get(key), str):
                    return {
                        "select": {"list": parts[0], "key": key, "value": item[key]},
                        "path": ".".join(parts[2:]),
                    }
    return {"select": None, "path": path}


def evaluate(expect, resolve):
    """Decide one expectation. ``resolve(operand_spec)`` returns the evidence it refers to."""
    op = expect["op"]
    if op in {"abs_ge", "share_ge"} and expect.get("threshold") is None:
        raise HypothesisError("THRESHOLD_REQUIRED")
    if op in {"abs_gt", "share_ge", "same_sign"} and expect.get("b") is None:
        raise HypothesisError("OPERAND_B_REQUIRED")
    if op == "rank_le" and (not expect["a"].get("select") or not expect.get("k")):
        raise HypothesisError("RANK_NEEDS_SELECT_AND_K")
    threshold = Decimal(expect["threshold"]) if expect.get("threshold") is not None else None
    if op == "share_ge" and not (0 < threshold <= 1):
        raise HypothesisError("THRESHOLD_OUT_OF_RANGE")
    if op == "abs_ge" and threshold < 0:
        raise HypothesisError("THRESHOLD_OUT_OF_RANGE")
    records, values, derived = [], [], None
    try:
        names = ("a",) if op == "rank_le" else ("a", "b")
        for name in names:
            spec = expect.get(name)
            if spec is None:
                continue
            ev = resolve(spec)
            if op == "rank_le":
                select = spec["select"]
                try:
                    _, index = locate(ev, {**spec, "path": "", "_rank": True})
                except Outcome as outcome:
                    items = ev["payload"].get(select["list"]) or []
                    if len(items) < expect["k"]:
                        raise Outcome("inconclusive", "NOT_FOUND") from None
                    raise outcome from None
                if rule_for(ev["tool"], f"{select['list']}.{index}.{select['key']}") is None:
                    raise HypothesisError("PATH_NOT_ALLOWED")
                records.append(
                    {
                        "evidence_id": ev["evidence_id"],
                        "tool": ev["tool"],
                        "args": ev.get("args", {}),
                        "select": select,
                        "path": "",
                        "rank": index + 1,
                    }
                )
                raise Outcome("supported" if index < expect["k"] else "refuted")
            try:
                path, _ = locate(ev, spec)
            except Outcome as missing:
                if name == "a" and op in LARGE and complete(ev, spec):
                    # The list holds every element with a value; absence means none at all.
                    raise Outcome("refuted", "NOT_PRESENT") from None
                raise missing from None
            try:
                item = operand(ev, path)
            except DeriveError as error:
                if error.code in INVALID:
                    raise HypothesisError(error.code) from None
                raise Outcome("inconclusive", error.code) from None
            values.append(item)
            records.append(
                {
                    "evidence_id": ev["evidence_id"],
                    "tool": ev["tool"],
                    "args": ev.get("args", {}),
                    **anchor(ev, path),
                    "value": {**public(item), "signed": item["change"]},
                }
            )
        a = values[0]
        b = values[1] if len(values) > 1 else None
        if op == "gt" and b is None and not a["change"] and (threshold or 0) <= 0:
            # "net sales > 0" is true almost by construction for a level: not a hypothesis.
            # "gross profit < 0" is a real claim and stays allowed.
            raise HypothesisError("TRIVIAL_PREDICATE")
        if b is not None and a["unit"] != b["unit"]:
            raise HypothesisError("UNIT_MISMATCH")
        if any(v["low"] and v["change"] for v in values):
            raise Outcome("inconclusive", "LOW_SAMPLE")
        with localcontext() as context:
            context.prec = 70
            x = a["value"]
            reference = b["value"] if b is not None else (threshold or Decimal(0))
            if op == "gt":
                state = x > reference
            elif op == "lt":
                state = x < reference
            elif op == "abs_ge":
                state = abs(x) >= threshold
            elif op == "abs_gt":
                state = abs(x) > abs(reference)
            elif op == "same_sign":
                if x == 0 or reference == 0:
                    raise Outcome("inconclusive", "ZERO_VALUE")
                state = (x > 0) == (reference > 0)
            else:
                try:
                    derived = compute("share", a, b)
                except DeriveError as error:
                    if error.code in INVALID:
                        raise HypothesisError(error.code) from None
                    if error.code != "SHARE_OUT_OF_RANGE":
                        raise Outcome("inconclusive", error.code) from None
                    # A part larger than the total (others moved the other way) is more than
                    # concentrated: the share exceeds every threshold. Keep the raw ratio.
                    derived = {
                        "value": number_text(abs(x) / abs(reference)),
                        "unit": "ratio",
                        "quality": "estimated"
                        if "estimated" in {a["quality"], b["quality"]}
                        else "confirmed",
                        "signed": False,
                    }
                state = Decimal(derived["value"]) >= threshold
        outcome = Outcome("supported" if state else "refuted")
    except Outcome as decided:
        outcome = decided
    quality = (
        "estimated"
        if any(r.get("value", {}).get("quality") == "estimated" for r in records)
        else "confirmed"
    )
    return {
        "state": outcome.state,
        "reason": outcome.reason,
        "quality": quality,
        "operands": records,
        "derived": derived,
    }


def anchored_spec(test, expect, operands):
    """Spec that can be re-run later: every operand names its tool call and a keyed select."""
    stored = {"op": expect["op"], "threshold": expect.get("threshold"), "k": expect.get("k")}
    for name, record in zip(("a", "b"), operands, strict=False):
        stored[name] = {
            "tool": record["tool"],
            "arguments": record["args"],
            "select": record.get("select"),
            "path": record.get("path", ""),
        }
    stored.setdefault("b", None)
    return {"test": test, "expect": stored}


def run_test(registry, parsed):
    """Execute ``test_hypothesis`` for the registry. Returns the verdict payload."""
    from app.reports.evidence import context as grammar_context
    from app.reports.grammar import check_sentence
    from app.reports.tools import TOOLS, ToolError

    test = parsed["test"]
    if test["tool"] not in TOOLS or test["tool"] in TEST_TOOLS_EXCLUDED:
        raise ToolError("TEST_TOOL_NOT_ALLOWED")
    result = registry.context["result"]
    statement = None
    if parsed.get("statement") is not None:
        ctx = grammar_context(
            registry.known(),
            result["currency"],
            result["currency_exponent"],
            registry.context.get("language", "zh"),
            registry.include_names,
        )
        issues, rendered = check_sentence(parsed["statement"], "statement", ctx, False)
        if issues:
            # The first grammar code tells the model what to fix (e.g. an unbound SKU).
            raise ToolError("INVALID_STATEMENT:" + issues[0]["code"])
        statement = rendered
    test_ev = registry.execute(test["tool"], arguments(test["arguments"]), core=True)

    def resolve(spec):
        if spec.get("source") == "test":
            return test_ev
        found = registry.lookup(spec.get("source"))
        if found is None:
            raise HypothesisError("UNKNOWN_EVIDENCE")
        return found

    expect = parsed["expect"]
    sources = [expect["a"].get("source")] + ([expect["b"].get("source")] if expect.get("b") else [])
    if "test" not in sources:
        raise ToolError("PREDICATE_MUST_USE_TEST")
    try:
        verdict = evaluate(expect, resolve)
    except HypothesisError as error:
        raise ToolError("INVALID_PREDICATE_" + error.code) from None
    return {
        "id": parsed["id"],
        "wave": parsed.get("wave", 1),
        **verdict,
        "statement": statement["text"] if statement else parsed.get("statement_text"),
        "statement_refs": statement["evidence_refs"] if statement else [],
        "test": {"tool": test["tool"], "arguments": test_ev.get("args", {})},
        "test_evidence_id": test_ev["evidence_id"],
        "op": expect["op"],
        "threshold": expect.get("threshold"),
        "k": expect.get("k"),
        "spec": anchored_spec(
            {"tool": test["tool"], "arguments": test_ev.get("args", {})},
            expect,
            verdict["operands"],
        ),
    }


def recheck(registry, parsed):
    """Re-run earlier hypotheses of this report series on the current data."""
    from app.reports.tools import ToolError

    items = []
    for item in parsed["items"]:
        expect = dict(item["spec"]["expect"])

        def resolve(spec):
            return registry.execute(spec["tool"], spec.get("arguments") or {}, core=True)

        try:
            verdict = evaluate(expect, resolve)
            state, reason = verdict["state"], verdict["reason"]
            quality = verdict["quality"]
        except (HypothesisError, ToolError) as error:
            state, reason, quality = "inconclusive", "TEST_FAILED:" + error.code, "confirmed"
        items.append(
            {
                "id": item["id"],
                "statement": item["statement"],
                "previous_state": item["previous_state"],
                "state": state,
                "reason": reason,
                "quality": quality,
                "source_report_id": item["source_report_id"],
            }
        )
    return {"items": items}


# ----------------------------------------------------------------- server candidates
STATEMENTS = {
    "zh": {
        "orders": "净销售额的变化主要来自支付订单量的变化，而不是客单价。",
        "top_contributor": "净销售额的变化主要集中在单个商品上。",
        "refund_concentrated": "累计退款主要集中在退款最多的商品上。",
        "refund_rate": "退款占比的变化主要来自单品退款率的变化，而不是商品结构变化。",
        "margin_mix": "毛利率的变化主要来自商品结构变化，而不是单品毛利率变化。",
        "aov_price": "客单价的变化主要来自件单价的变化，而不是每单件数。",
    },
    "en": {
        "orders": "The net sales change comes mainly from paid order count, not order value.",
        "top_contributor": "The net sales change is concentrated in a single product.",
        "refund_concentrated": "Refunds are concentrated in the product with the most refunds.",
        "refund_rate": "The refund share moved mainly with product refund rates, not with "
        "product mix.",
        "margin_mix": "The margin change comes mainly from product mix, not product margins.",
        "aov_price": "Order value moved mainly with price per unit, not units per order.",
    },
}


def _candidate(key, language, tool, args, op, a, b=None, threshold=None):
    return {
        "id": "h_srv_" + key,
        "statement": {"template": STATEMENTS[language][key], "bindings": []},
        "test": {"tool": tool, "arguments": args},
        "expect": {
            "op": op,
            "a": {"source": "test", "path": a, "select": None},
            "b": {"source": "test", "path": b, "select": None} if b else None,
            "threshold": threshold,
            "k": None,
        },
    }


def candidates(core, result, language="zh"):
    """Server-proposed hypotheses for triggered rules; tested before the model starts."""
    checks = core["detect_anomalies"]["payload"]["checks"]
    triggered = {c["code"] for c in checks if c["state"] == "triggered"}
    comparison = result.get("comparison") or {}
    decompositions = result.get("decompositions") or {}
    contributions = result.get("contributions") or {}
    found = []
    if "SALES_CHANGE" in triggered and (contributions.get("effects") or {}):
        found.append(
            _candidate(
                "orders",
                language,
                "decompose_sales_change",
                {},
                "abs_gt",
                "effects.order_effect_minor",
                "effects.aov_effect_minor",
            )
        )
        total = contributions.get("total_minor")
        side = "decliners" if total is not None and Decimal(str(total)) < 0 else "gainers"
        if contributions.get(side):
            found.append(
                _candidate(
                    "top_contributor",
                    language,
                    "decompose_sales_change",
                    {},
                    "share_ge",
                    f"{side}.0.sales_contribution_minor",
                    "total_minor",
                    "0.5",
                )
            )
        if (decompositions.get("aov") or {}).get("available"):
            found.append(
                _candidate(
                    "aov_price",
                    language,
                    "decompose_metric_change",
                    {"metric": "aov"},
                    "abs_gt",
                    "price_effect_minor",
                    "basket_effect_minor",
                )
            )
    if "HIGH_REFUND" in triggered:
        found.append(
            _candidate(
                "refund_concentrated",
                language,
                "refund_breakdown",
                {"by": "sku", "top_k": 5},
                "share_ge",
                "items.0.metrics.refund_amount",
                "total.metrics.refund_amount",
                "0.5",
            )
        )
        if (decompositions.get("refund_amount_rate") or {}).get("available"):
            found.append(
                _candidate(
                    "refund_rate",
                    language,
                    "decompose_metric_change",
                    {"metric": "refund_amount_rate"},
                    "abs_gt",
                    "rate_effect_pp",
                    "mix_effect_pp",
                )
            )
    margin = (comparison.get("gross_margin") or {}).get("delta_pp")
    if ("MARGIN_DROP" in triggered or (margin is not None and abs(Decimal(margin)) >= 2)) and (
        decompositions.get("gross_margin") or {}
    ).get("available"):
        found.append(
            _candidate(
                "margin_mix",
                language,
                "decompose_metric_change",
                {"metric": "gross_margin"},
                "abs_gt",
                "mix_effect_pp",
                "rate_effect_pp",
            )
        )
    return found[:5]


def verdict_summary(evidence):
    """Compact model-facing view of a verdict record."""
    payload = evidence["payload"]
    return {
        "evidence_id": evidence["evidence_id"],
        "id": payload["id"],
        "wave": payload["wave"],
        "statement": payload["statement"],
        "state": payload["state"],
        "reason": payload["reason"],
        "quality": payload["quality"],
        "test_evidence_id": payload["test_evidence_id"],
        "derived": payload["derived"],
        "values": [
            {"path": f"operands.{i}.value", **(o.get("value") or {"rank": o.get("rank")})}
            for i, o in enumerate(payload["operands"])
        ],
    }


__all__ = ["STATES", "candidates", "evaluate", "number_text", "recheck", "run_test", "seed"]


def seed(registry, core, language="zh", prior=None):
    """Server-side hypotheses before the model starts.

    Candidates for triggered rules are tested first, so even a run without a model (or a model
    that cannot plan) gets basic depth; earlier supported or refuted hypotheses of the report
    series are re-checked on the current data. Returns (verdict records, recheck record or None).
    """
    from app.reports.tools import ToolError

    verdicts = []
    for spec in candidates(core, registry.context["result"], language):
        try:
            verdicts.append(registry.execute("test_hypothesis", {**spec, "wave": 0}, core=True))
        except ToolError:
            continue
    rechecked = None
    if prior:
        try:
            rechecked = registry.execute("recheck_hypotheses", {"items": prior}, core=True)
        except ToolError:
            rechecked = None
    return verdicts, rechecked
