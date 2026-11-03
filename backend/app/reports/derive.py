"""Server-side arithmetic over two evidence values.

Used by computed bindings (a binding with ``derive``), the ``derive`` tool and hypothesis tests.
Only whitelisted numeric paths can be operands, and unit rules decide which operations make sense,
so "refunds as a share of order value" and similar nonsense cannot be produced.
"""

import hashlib
import json
import re
import uuid
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext

from app.reports.grammar import UNITS, rule_for, walk

OPS = ("diff", "ratio", "multiple", "share")
NUMERIC = {
    "metric",
    "delta",
    "ratio",
    "signed_ratio",
    "pp",
    "money",
    "signed_money",
    "count",
    "derived",
}
# Kinds that describe a change rather than a level: small samples make them unreliable.
CHANGE_KINDS = {"delta", "signed_ratio", "pp", "signed_money"}
KIND_UNITS = {
    "ratio": "ratio",
    "signed_ratio": "ratio",
    "pp": "pp",
    "money": "minor_currency",
    "signed_money": "minor_currency",
    "count": "count",
}
# Paths that hold a whole-store total; ``share`` divides by one of these.
TOTALS = {
    "calculate_metrics": re.compile(r"^(current|previous)\.metrics\.[a-z_]+$"),
    "refund_breakdown": re.compile(r"^total\.metrics\.[a-z_]+$"),
    "decompose_sales_change": re.compile(r"^total_minor$"),
    "decompose_metric_change": re.compile(r"^(delta_pp|delta_minor)$"),
    "get_history": re.compile(r"^windows\.\d{1,3}\.metrics\.[a-z_]+$"),
}
NAMESPACE = uuid.UUID("5d8a4c1e-3b7f-4f0e-9a51-1c2b7e6f9d30")


class DeriveError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def number_text(value):
    if value.as_tuple().exponent < -12:
        value = value.quantize(Decimal("0.000000000001"), rounding=ROUND_HALF_UP)
    return format(value.normalize() if value == value.to_integral() else value, "f")


def flagged(payload, path, key, values):
    """True when the nearest object on the way to ``path`` (or the leaf) that sets ``key`` has
    it in ``values``. A nearer setting wins: a verdict marked estimated because one operand is
    estimated still has a confirmed operand."""
    node, found = payload, None
    parts = path.split(".") if path else []
    for part in [None, *parts]:
        if part is not None:
            if isinstance(node, list) and part.isdigit() and int(part) < len(node):
                node = node[int(part)]
            elif isinstance(node, dict) and part in node:
                node = node[part]
            else:
                break
        if isinstance(node, dict) and isinstance(node.get(key), str):
            found = node[key]
    return found in values


def low_sample(payload, path):
    return flagged(payload, path, "sample", {"low"})


def operand(ev, path):
    """Resolve one numeric operand: value, unit, quality and what it measures."""
    rule = rule_for(ev["tool"], path)
    if rule is None:
        raise DeriveError("PATH_NOT_ALLOWED")
    kind, metric = rule
    if kind not in NUMERIC:
        raise DeriveError("NOT_A_NUMBER")
    try:
        leaf = walk(ev["payload"], path)
    except (KeyError, TypeError):
        raise DeriveError("PATH_NOT_FOUND") from None
    quality = "estimated" if flagged(ev["payload"], path, "quality", {"estimated"}) else None
    if kind in {"metric", "derived"}:
        if not isinstance(leaf, dict):
            raise DeriveError("NOT_A_NUMBER")
        unit, value = leaf.get("unit"), leaf.get("value")
        quality = leaf.get("quality") if leaf.get("quality") != "confirmed" else quality
        if kind == "metric" and metric is None:
            metric = path.rsplit(".", 1)[-1]
    elif kind == "delta":
        unit, value = UNITS[metric], leaf
    else:
        unit, value = KIND_UNITS[kind], leaf
    if value is None or quality == "unavailable":
        raise DeriveError("UNAVAILABLE_VALUE")
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise DeriveError("NOT_A_NUMBER") from None
    if not number.is_finite():
        raise DeriveError("NOT_A_NUMBER")
    if kind == "derived" and metric is None:
        metric = ev["payload"].get("metric") if isinstance(ev["payload"], dict) else None
    parts = path.split(".")
    return {
        "evidence_id": ev["evidence_id"],
        "path": path,
        "kind": kind,
        "value": number,
        "unit": unit,
        "quality": quality or "confirmed",
        "metric": metric,
        "period": next((p for p in parts if p in {"current", "previous"}), None),
        "total": bool(TOTALS.get(ev["tool"]) and TOTALS[ev["tool"]].match(path)),
        "low": low_sample(ev["payload"], path),
        "change": kind in CHANGE_KINDS or (kind == "derived" and bool(leaf.get("signed"))),
    }


def compute(op, a, b):
    """Return {"value", "unit", "quality", "signed"} for ``a <op> b`` or raise DeriveError."""
    if op not in OPS:
        raise DeriveError("UNKNOWN_OP")
    if a["unit"] != b["unit"]:
        raise DeriveError("UNIT_MISMATCH")
    with localcontext() as context:
        context.prec = 70
        x, y = a["value"], b["value"]
        if op == "diff":
            if a["metric"] != b["metric"] or (a["metric"] is None and a["kind"] != b["kind"]):
                raise DeriveError("METRIC_MISMATCH")
            value, unit = x - y, a["unit"]
            if unit == "ratio":
                value, unit = value * 100, "pp"
            signed = True
        else:
            if y == 0:
                raise DeriveError("ZERO_BASE")
            if op == "share":
                same = a["evidence_id"] == b["evidence_id"]
                if a["metric"] != b["metric"] or (not same and a["metric"] is None):
                    raise DeriveError("METRIC_MISMATCH")
                if not same and not b["total"]:
                    raise DeriveError("NOT_A_TOTAL")
                if a["period"] != b["period"]:
                    raise DeriveError("PERIOD_MISMATCH")
                if (x < 0) != (y < 0) and x != 0:
                    raise DeriveError("SIGN_MISMATCH")
                x, y = abs(x), abs(y)
                if x > y:
                    raise DeriveError("SHARE_OUT_OF_RANGE")
            elif y < 0:
                raise DeriveError("NEGATIVE_BASE")
            elif op == "multiple" and x < 0:
                raise DeriveError("NEGATIVE_VALUE")
            value = x / y
            unit = "multiple" if op == "multiple" else "ratio"
            signed = False
        return {
            "value": number_text(value),
            "unit": unit,
            "quality": "estimated" if "estimated" in {a["quality"], b["quality"]} else "confirmed",
            "signed": signed,
        }


def public(item):
    return {
        "value": number_text(item["value"]),
        "unit": item["unit"],
        "quality": item["quality"],
    }


def derived_record(op, a_ev, a_path, b_ev, b_path):
    """Evidence record for a computed binding. The id is deterministic, so repeats collapse."""
    a, b = operand(a_ev, a_path), operand(b_ev, b_path)
    result = compute(op, a, b)
    args = {
        "op": op,
        "a": {"evidence_id": a_ev["evidence_id"], "path": a_path, "hash": a_ev["result_hash"]},
        "b": {"evidence_id": b_ev["evidence_id"], "path": b_path, "hash": b_ev["result_hash"]},
    }
    payload = {"op": op, "a": public(a), "b": public(b), "result": result}
    args_hash = digest(args)
    return (
        {
            "evidence_id": str(uuid.uuid5(NAMESPACE, f"{a_ev['report_id']}:{args_hash}")),
            "report_id": a_ev["report_id"],
            "run_id": a_ev.get("run_id"),
            "dataset_id": a_ev["dataset_id"],
            "scope": a_ev["scope"],
            "tool": "derive",
            "tool_version": "3.0",
            "metric_definition_version": a_ev.get("metric_definition_version"),
            "engine_version": a_ev.get("engine_version"),
            "args": args,
            "args_hash": args_hash,
            "payload": payload,
            "result_hash": digest(payload),
        },
        a,
        b,
    )
