"""Evidence-bound sentence grammar (v3).

The model writes sentence templates with ``{{name}}`` placeholders. Every placeholder is bound to
an evidence record and a whitelisted path inside that record's payload; the server resolves the
path, checks that the requested format matches the value's type and renders the final text.
Numbers, SKUs, dates and labels therefore never come from model prose.

v3 adds computed bindings (``derive``: diff, ratio, multiple or share of two bound values, checked
by unit rules in ``derive.py``), the ``multiple`` format, labels for hypothesis states and trend
directions, and a small-sample rule: a SKU-level change measured on few orders cannot carry an
observation on its own.
"""

import difflib
import re
from decimal import Decimal, InvalidOperation, localcontext

PLACEHOLDER = re.compile(r"\{\{([a-z][a-z0-9_]{0,19})\}\}")
FORMATS = ("money", "count", "percent", "pp", "multiple", "entity", "date", "label", "note")
UNITS = {
    "gross_sales": "minor_currency",
    "refund_amount": "minor_currency",
    "net_sales": "minor_currency",
    "paid_orders": "count",
    "paid_units": "count",
    "aov": "minor_currency",
    "gross_aov": "minor_currency",
    "net_cogs": "minor_currency",
    "gross_profit": "minor_currency",
    "gross_margin": "ratio",
    "refund_amount_rate": "ratio",
    "refunded_order_rate": "ratio",
    "cost_line_coverage": "ratio",
    "cost_amount_coverage": "ratio",
}

LABELS = {
    "metric": {
        "zh": {
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
            "gross_aov": "退款前客单价",
            "refunded_order_rate": "退款订单占比",
            "cost_line_coverage": "成本明细覆盖率",
            "cost_amount_coverage": "成本金额覆盖率",
        },
        "en": {
            "net_sales": "net sales",
            "paid_orders": "paid orders",
            "aov": "net average order value",
            "gross_profit": "product gross profit",
            "gross_margin": "product gross margin",
            "refund_amount_rate": "refund share of sales",
            "gross_sales": "paid sales before refunds",
            "refund_amount": "refunds on paid orders",
            "net_cogs": "net cost of goods",
            "paid_units": "paid units",
            "gross_aov": "average order value before refunds",
            "refunded_order_rate": "refunded order share",
            "cost_line_coverage": "cost line coverage",
            "cost_amount_coverage": "cost amount coverage",
        },
    },
    "rule": {
        "zh": {
            "SALES_CHANGE": "净销售额波动",
            "HIGH_REFUND": "退款占比偏高",
            "MARGIN_DROP": "毛利率下降",
            "NEGATIVE_PROFIT": "负毛利商品",
            "CONCENTRATION": "销售集中",
            "DAILY_MAD": "日销售离群",
        },
        "en": {
            "SALES_CHANGE": "net sales swing",
            "HIGH_REFUND": "high refund share",
            "MARGIN_DROP": "margin decline",
            "NEGATIVE_PROFIT": "negative-margin products",
            "CONCENTRATION": "sales concentration",
            "DAILY_MAD": "daily sales outlier",
        },
    },
    "rule_state": {
        "zh": {
            "triggered": "已触发",
            "clear": "未触发",
            "insufficient_data": "样本或数据不足",
            "insufficient_baseline": "历史基线不足",
        },
        "en": {
            "triggered": "triggered",
            "clear": "clear",
            "insufficient_data": "insufficient data",
            "insufficient_baseline": "insufficient baseline",
        },
    },
    "warning": {
        "zh": {
            "SMALL_SAMPLE": "本期订单样本偏少",
            "INCOMPLETE_COVERAGE": "本期数据覆盖不完整",
            "COMPARISON_INCOMPLETE": "比较期数据覆盖不完整",
            "COST_MISSING": "部分商品缺少成本",
            "RESTOCK_ESTIMATED": "退款回库数量未知",
            "REFUND_UNKNOWN": "累计退款未知",
            "REFUND_ALLOCATED": "退款经过分摊",
        },
        "en": {
            "SMALL_SAMPLE": "small order sample",
            "INCOMPLETE_COVERAGE": "incomplete coverage in the current period",
            "COMPARISON_INCOMPLETE": "incomplete coverage in the comparison period",
            "COST_MISSING": "some products lack costs",
            "RESTOCK_ESTIMATED": "restocked quantity unknown",
            "REFUND_UNKNOWN": "cumulative refunds unknown",
            "REFUND_ALLOCATED": "refunds were allocated",
        },
    },
    "followup": {
        "zh": {"improved": "已改善", "not_improved": "未改善", "insufficient_data": "数据不足"},
        "en": {
            "improved": "improved",
            "not_improved": "not improved",
            "insufficient_data": "insufficient data",
        },
    },
    "hypothesis_state": {
        "zh": {"supported": "数据支持", "refuted": "已排除", "inconclusive": "无法判断"},
        "en": {
            "supported": "supported by data",
            "refuted": "ruled out",
            "inconclusive": "inconclusive",
        },
    },
    "direction": {
        "zh": {"up": "上升", "down": "下降", "flat": "持平"},
        "en": {"up": "rising", "down": "falling", "flat": "flat"},
    },
    "note_kind": {
        "zh": {
            "promotion": "促销",
            "holiday": "节假日",
            "stockout": "缺货",
            "pricing": "调价",
            "other": "其他",
        },
        "en": {
            "promotion": "promotion",
            "holiday": "holiday",
            "stockout": "stockout",
            "pricing": "price change",
            "other": "other",
        },
    },
}

M = r"(?P<m>[a-z_]+)"
N = r"\d{1,3}"
COMPARISON = [
    (rf"comparison\.{M}\.change_rate", "signed_ratio"),
    (rf"comparison\.{M}\.delta_pp", "pp"),
    (rf"comparison\.{M}\.delta", "delta"),
]
# Bindable paths per tool. Anything else (thresholds, hashes, raw options) cannot reach prose.
RULES = {
    "calculate_metrics": [(rf"(current|previous)\.metrics\.{M}", "metric")],
    "compare_periods": COMPARISON,
    "get_sales_trend": [
        (rf"points\.{N}\.start", "date"),
        (rf"points\.{N}\.metrics\.{M}", "metric"),
    ],
    "rank_products": [
        (rf"items\.{N}\.sku", "sku"),
        (rf"items\.{N}\.product_name", "name"),
        (rf"items\.{N}\.(current|previous)\.metrics\.{M}", "metric"),
        *[(rf"items\.{N}\." + pattern, kind) for pattern, kind in COMPARISON],
        (r"total", "count"),
    ],
    "decompose_sales_change": [
        (rf"(gainers|decliners)\.{N}\.sku", "sku"),
        (rf"(gainers|decliners)\.{N}\.product_name", "name"),
        (rf"(gainers|decliners)\.{N}\.sales_contribution_minor", "signed_money"),
        (r"effects\.(order_effect_minor|aov_effect_minor)", "signed_money"),
        (r"total_minor", "signed_money"),
    ],
    "detect_anomalies": [
        (rf"checks\.{N}\.code", "label:rule"),
        (rf"checks\.{N}\.state", "label:rule_state"),
        (rf"checks\.{N}\.values\.change_rate", "signed_ratio"),
        (rf"checks\.{N}\.values\.(rate|top_three_share)", "ratio"),
        (rf"checks\.{N}\.values\.delta_pp", "pp"),
        (rf"checks\.{N}\.values\.items\.{N}\.sku", "sku"),
        (rf"checks\.{N}\.values\.items\.{N}\.product_name", "name"),
        (rf"checks\.{N}\.values\.items\.{N}\.date", "date"),
        (rf"checks\.{N}\.values\.items\.{N}\.current\.metrics\.{M}", "metric"),
    ],
    "get_data_quality": [
        (rf"warnings\.{N}", "label:warning"),
        (r"quality\.(missing_cost_rows|missing_cost_skus|estimated_restock_rows)", "count"),
        (r"quality\.(missing_cost_paid_minor|estimated_restock_paid_minor)", "money"),
        (r"excluded_rows", "count"),
    ],
    "inspect_sku": [
        (r"sku", "sku"),
        (r"product_name", "name"),
        (rf"(current|previous)\.metrics\.{M}", "metric"),
        *COMPARISON,
        (rf"trend\.{N}\.start", "date"),
        (rf"trend\.{N}\.metrics\.{M}", "metric"),
    ],
    "refund_breakdown": [
        (rf"items\.{N}\.sku", "sku"),
        (rf"items\.{N}\.product_name", "name"),
        (rf"items\.{N}\.start", "date"),
        (rf"items\.{N}\.metrics\.{M}", "metric"),
        (rf"items\.{N}\.previous\.metrics\.{M}", "metric"),
        *[(rf"items\.{N}\." + pattern, kind) for pattern, kind in COMPARISON],
        (rf"total\.metrics\.{M}", "metric"),
        (rf"total\.previous\.metrics\.{M}", "metric"),
        *[(r"total\." + pattern, kind) for pattern, kind in COMPARISON],
    ],
    "decompose_metric_change": [
        (r"metric", "label:metric"),
        (r"(delta_pp|mix_effect_pp|rate_effect_pp|other_pp)", "pp"),
        (r"(delta_minor|price_effect_minor|basket_effect_minor)", "signed_money"),
        (rf"items\.{N}\.sku", "sku"),
        (rf"items\.{N}\.product_name", "name"),
        (rf"items\.{N}\.(mix_effect_pp|rate_effect_pp|total_effect_pp)", "pp"),
        (rf"items\.{N}\.(current_share|previous_share|current_rate|previous_rate)", "ratio"),
    ],
    "get_history": [
        (rf"windows\.{N}\.(start|end_exclusive)", "date"),
        (rf"windows\.{N}\.metrics\.{M}", "metric"),
        (rf"streaks\.{M}\.periods", "count"),
        (rf"streaks\.{M}\.direction", "label:direction"),
        (r"window_days", "count"),
    ],
    "derive": [(r"result", "derived")],
    "test_hypothesis": [
        (r"state", "label:hypothesis_state"),
        (r"derived", "derived"),
        (rf"operands\.{N}\.value", "derived"),
    ],
    "recheck_hypotheses": [
        (rf"items\.{N}\.statement", "note"),
        (rf"items\.{N}\.(state|previous_state)", "label:hypothesis_state"),
    ],
    "cost_coverage": [
        (r"summary\.(missing_cost_rows|missing_cost_skus|estimated_restock_rows)", "count"),
        (r"summary\.(missing_cost_paid_minor|estimated_restock_paid_minor)", "money"),
        (rf"items\.{N}\.sku", "sku"),
        (rf"items\.{N}\.product_name", "name"),
        (rf"items\.{N}\.missing_cost_rows", "count"),
        (rf"items\.{N}\.metrics\.{M}", "metric"),
    ],
    "explain_metric": [(r"metric", "label:metric")],
    "check_recommendation": [
        (rf"items\.{N}\.verification_metric", "label:metric"),
        (rf"items\.{N}\.state", "label:followup"),
        (rf"items\.{N}\.(baseline|current)", "metric"),
        (rf"items\.{N}\.change_rate", "signed_ratio"),
        (rf"items\.{N}\.action_text", "note"),
        (rf"items\.{N}\.source_period\.{N}", "date"),
    ],
    "get_merchant_notes": [
        (rf"items\.{N}\.text", "note"),
        (rf"items\.{N}\.kind", "label:note_kind"),
        (rf"items\.{N}\.(start|end_exclusive)", "date"),
    ],
}
COMPILED = {
    tool: [(re.compile("^" + pattern + "$"), kind) for pattern, kind in rules]
    for tool, rules in RULES.items()
}
FORBIDDEN = re.compile(
    r"[两半倍%％<>{}]|https?://|www\.|SKU|保证|必然|确定导致|一定会|"
    r"\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|"
    r"twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|"
    r"million|billion|percent|double|triple|half|quarter|guarantee[sd]?)\b",
    re.I,
)
ESTIMATED = {"zh": "（估算）", "en": " (est.)"}


class EvidenceError(ValueError):
    """Validation failure with machine-readable locations for a targeted repair prompt."""

    def __init__(self, issues):
        self.issues = issues[:12]
        super().__init__(issues[0]["code"] if issues else "EVIDENCE_INVALID")


def issue(at, code, hint=""):
    return {"at": at, "code": code, "hint": hint}


def rule_for(tool, path):
    for pattern, kind in COMPILED.get(tool, []):
        match = pattern.match(path)
        if match:
            metric = match.groupdict().get("m")
            if metric is not None and metric not in UNITS:
                return None
            return kind, metric
    return None


def walk(payload, path):
    value = payload
    for part in path.split("."):
        if isinstance(value, list):
            if not part.isdigit() or int(part) >= len(value):
                raise KeyError(path)
            value = value[int(part)]
        elif isinstance(value, dict) and part in value:
            value = value[part]
        else:
            raise KeyError(path)
    return value


DERIVED_FORMATS = {
    "minor_currency": "money",
    "count": "count",
    "ratio": "percent",
    "pp": "pp",
    "multiple": "multiple",
}


def expected_format(kind, metric, leaf):
    if kind == "derived":
        return DERIVED_FORMATS.get(leaf.get("unit")) if isinstance(leaf, dict) else None
    if kind == "metric":
        if not isinstance(leaf, dict) or leaf.get("unit") not in {
            "minor_currency",
            "count",
            "ratio",
        }:
            return None
        return {"minor_currency": "money", "count": "count", "ratio": "percent"}[leaf["unit"]]
    if kind == "delta":
        return {"minor_currency": "money", "count": "count"}.get(UNITS.get(metric))
    return {
        "ratio": "percent",
        "signed_ratio": "percent",
        "pp": "pp",
        "money": "money",
        "signed_money": "money",
        "count": "count",
        "sku": "entity",
        "name": "entity",
        "date": "date",
        "note": "note",
    }.get(kind, "label" if kind.startswith("label:") else None)


def decimal_text(value, places, signed):
    text = f"{value:,.{places}f}"
    return "+" + text if signed and value > 0 else text


def render_value(kind, leaf, fmt, ctx, estimated=False):
    language = ctx["language"]
    signed = kind in {"signed_ratio", "signed_money", "pp", "delta"}
    if kind in {"metric", "derived"}:
        if leaf.get("value") is None:
            raise ValueError("UNAVAILABLE_VALUE")
        estimated = estimated or leaf.get("quality") == "estimated"
        signed = signed or bool(leaf.get("signed"))
        leaf = leaf["value"]
    if fmt in {"money", "count", "percent", "pp", "multiple"}:
        try:
            with localcontext() as context:
                context.prec = 70
                amount = Decimal(str(leaf))
                if fmt == "money":
                    exponent = ctx["exponent"]
                    text = (
                        ctx["currency"]
                        + " "
                        + decimal_text(amount / (Decimal(10) ** exponent), exponent, signed)
                    )
                elif fmt == "percent":
                    text = decimal_text(amount * 100, 2, signed) + "%"
                elif fmt == "pp":
                    number = decimal_text(amount, 2, signed)
                    text = number + (" 个百分点" if language == "zh" else " pp")
                elif fmt == "multiple":
                    number = decimal_text(amount, 2, False)
                    text = number + (" 倍" if language == "zh" else "×")
                else:
                    text = decimal_text(amount, 0, signed)
        except (InvalidOperation, ValueError, TypeError):
            raise ValueError("NOT_A_NUMBER") from None
        return text + (ESTIMATED[language] if estimated else "")
    if fmt == "entity":
        if not isinstance(leaf, str) or not leaf.strip():
            raise ValueError("NOT_AN_ENTITY")
        return leaf[:160]
    if fmt == "date":
        if not isinstance(leaf, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}.*", leaf):
            raise ValueError("NOT_A_DATE")
        return leaf[:10]
    if fmt == "note":
        if not isinstance(leaf, str) or not leaf.strip():
            raise ValueError("NOT_A_NOTE")
        text = leaf.strip()
        text = text[:120] + ("…" if len(text) > 120 else "")
        return "“" + text + "”"
    domain = kind.split(":", 1)[1]
    label = LABELS[domain][language].get(leaf) if isinstance(leaf, str) else None
    if label is None:
        raise ValueError("UNKNOWN_LABEL")
    return label


def entities(evidence):
    """SKU/product strings that may only reach prose through an entity binding."""
    found = set()

    def visit(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"sku", "product_name"} and isinstance(item, str):
                    if 2 <= len(item.strip()) <= 200:
                        found.add(item.strip().lower())
                else:
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    for ev in evidence:
        visit(ev.get("payload"))
    return found


def free_text_issues(text, at, ctx, limit=300):
    if not isinstance(text, str) or not text.strip():
        return [issue(at, "EMPTY_TEXT")]
    if len(text) > limit:
        return [issue(at, "TEXT_TOO_LONG", f"max {limit} characters")]
    word = FORBIDDEN.search(text)
    if word or any(character.isnumeric() for character in text):
        # Names only what the rule matched, so a repair can act on it without echoing the reply.
        found = f'"{word.group(0)}"' if word else "a digit"
        return [
            issue(
                at,
                "UNBOUND_NUMBER_OR_CLAIM",
                f"found {found}; numbers, dates, percentages, URLs, the word SKU and certainty "
                "claims need bindings or other wording",
            )
        ]
    lowered = text.lower()
    if any(entity in lowered for entity in ctx["entities"]):
        return [issue(at, "UNBOUND_ENTITY", "name products through an entity binding")]
    return []


def node_paths(value, prefix="", depth=0):
    """Paths of every node (lists capped) for nearest-path repair hints."""
    if depth > 8:
        return
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else key
            yield path
            yield from node_paths(item, path, depth + 1)
    elif isinstance(value, list):
        for index, item in enumerate(value[:10]):
            path = f"{prefix}.{index}" if prefix else str(index)
            yield path
            yield from node_paths(item, path, depth + 1)


def nearest_path(ev, path):
    candidates = [p for p in node_paths(ev["payload"]) if rule_for(ev["tool"], p)]
    best = difflib.get_close_matches(path, candidates, n=1, cutoff=0.5)
    return best[0] if best else None


def path_hint(ev, path, message):
    best = nearest_path(ev, path)
    return message + (f"; closest bindable path: {best}" if best else "")


def computed(binding, ev, ctx):
    """Resolve a ``derive`` binding. Returns (kind, leaf, (in_low_item, is_change), record)."""
    from app.reports.derive import DeriveError, derived_record

    spec = binding["derive"]
    other = ctx["evidence"].get(spec["b"]["evidence_id"])
    if other is None:
        raise DeriveError("UNKNOWN_EVIDENCE")
    record, a, b = derived_record(spec["op"], ev, binding["path"], other, spec["b"]["path"])
    low = (a["low"] or b["low"], spec["op"] == "diff" or a["change"] or b["change"])
    return "derived", record["payload"]["result"], low, record


def check_sentence(sentence, at, ctx, require_binding):
    """Return (issues, rendered) for one sentence object (already schema-validated)."""
    from app.reports.derive import CHANGE_KINDS, DeriveError, flagged, low_sample

    template = sentence["template"]
    bindings = sentence["bindings"]
    issues = []
    names = PLACEHOLDER.findall(template)
    bound = [b["name"] for b in bindings]
    if require_binding and not bindings:
        issues.append(issue(at, "FACT_REQUIRES_BINDING", "observations need at least one binding"))
    if len(set(bound)) != len(bound) or sorted(names) != sorted(bound):
        issues.append(
            issue(at, "PLACEHOLDER_MISMATCH", "each {{name}} appears once and matches a binding")
        )
    issues += free_text_issues(PLACEHOLDER.sub("", template), at + ".template", ctx)
    values, refs, lows = {}, [], []
    for index, binding in enumerate(bindings):
        where = f"{at}.bindings[{index}]"
        ev = ctx["evidence"].get(binding["evidence_id"])
        if ev is None:
            issues.append(issue(where, "UNKNOWN_EVIDENCE", "use an evidence_id you were given"))
            continue
        rule = rule_for(ev["tool"], binding["path"])
        if rule is None:
            issues.append(
                issue(
                    where,
                    "PATH_NOT_ALLOWED",
                    path_hint(ev, binding["path"], f"path is not bindable for tool {ev['tool']}"),
                )
            )
            continue
        kind, metric = rule
        if kind == "name" and not ctx["include_names"]:
            issues.append(issue(where, "NAMES_NOT_AUTHORIZED", "bind the sku instead"))
            continue
        record = None
        if binding.get("derive"):
            try:
                kind, leaf, low, record = computed(binding, ev, ctx)
            except DeriveError as error:
                issues.append(issue(where, "DERIVE_" + error.code))
                continue
        else:
            try:
                leaf = walk(ev["payload"], binding["path"])
            except (KeyError, TypeError):
                issues.append(
                    issue(where, "PATH_NOT_FOUND", path_hint(ev, binding["path"], "no such path"))
                )
                continue
            low = (low_sample(ev["payload"], binding["path"]), kind in CHANGE_KINDS)
        fmt = expected_format(kind, metric, leaf)
        if fmt is None or fmt != binding["format"]:
            issues.append(issue(where, "WRONG_FORMAT", f"expected {fmt or 'nothing'}"))
            continue
        estimated = record is None and flagged(
            ev["payload"], binding["path"], "quality", {"estimated"}
        )
        try:
            values[binding["name"]] = render_value(kind, leaf, fmt, ctx, estimated)
        except ValueError as error:
            issues.append(issue(where, str(error)))
            continue
        refs.append(binding["evidence_id"])
        if record is not None:
            refs += [binding["derive"]["b"]["evidence_id"], record["evidence_id"]]
            ctx.setdefault("derived", {})[record["evidence_id"]] = record
        lows.append(low)
    # A change measured on a small-sample SKU needs at least one binding from outside such items.
    if (
        not issues
        and require_binding
        and any(item and change for item, change in lows)
        and all(item for item, _ in lows)
    ):
        issues.append(
            issue(
                at,
                "LOW_SAMPLE_ONLY",
                "a SKU-level change on few orders cannot carry this sentence alone; add a "
                "store-level binding or move it to hypotheses",
            )
        )
    if issues:
        return issues, None
    text = PLACEHOLDER.sub(lambda match: values[match.group(1)], template)
    return [], {
        "text": text,
        "evidence_refs": list(dict.fromkeys(refs)),
        "template": template,
        "bindings": bindings,
    }
