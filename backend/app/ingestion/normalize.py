import hashlib
import json
import re
from bisect import bisect_right
from collections import Counter, defaultdict
from datetime import UTC, datetime
from decimal import ROUND_FLOOR, Decimal, InvalidOperation, localcontext
from zoneinfo import ZoneInfo

SAFE_INTEGER = 2**53 - 1


def timestamp(value: str, timezone: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("/", "-").replace("Z", "+00:00"))
    except (ValueError, TypeError):
        raise ValueError("时间无法解析，请使用 YYYY-MM-DD 或完整 ISO 时间。") from None
    if parsed.tzinfo:
        return parsed.astimezone(UTC)
    zone = ZoneInfo(timezone)
    candidates = {
        parsed.replace(tzinfo=zone, fold=fold).astimezone(UTC)
        for fold in (0, 1)
        if parsed.replace(tzinfo=zone, fold=fold)
        .astimezone(UTC)
        .astimezone(zone)
        .replace(tzinfo=None)
        == parsed
    }
    if len(candidates) != 1:
        raise ValueError("本地时间不存在或存在夏令时歧义，请在源数据中明确 UTC 偏移。")
    return candidates.pop()


def number(value: str, separator=".") -> Decimal:
    if separator == ",":
        value = value.replace(",", ".")
    if not re.fullmatch(r"[+-]?\d+(\.\d+)?", value):
        raise ValueError("金额/数量格式不明确，不接受货币符号、千分位或科学计数。")
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise ValueError("数字无效。") from None
    if not result.is_finite() or abs(result) > SAFE_INTEGER or len(result.as_tuple().digits) > 28:
        raise ValueError("数字超出可安全处理的范围。")
    return result


def allocate(total: int, weights: list[Decimal], ids: list[str]) -> list[int]:
    with localcontext() as context:
        context.prec = 80
        denominator = sum(weights)
        if denominator <= 0 or any(w < 0 for w in weights):
            raise ValueError("订单分摊权重必须非负且合计大于零。")
        raw = [Decimal(total) * weight / denominator for weight in weights]
        base = [int(x.to_integral_value(rounding=ROUND_FLOOR)) for x in raw]
        ranked = sorted(range(len(base)), key=lambda i: (-(raw[i] - base[i]), ids[i]))
        for i in ranked[: total - sum(base)]:
            base[i] += 1
        return base


def normalize(
    parsed: dict, kind: str, config: dict, resolutions: dict, file_hash: str, costs: list[dict]
) -> dict:
    options, columns = config["options"], config["columns"]
    issues, output = [], []
    excluded = set(resolutions.get("excluded_rows", []))
    ack = set(resolutions.get("acknowledged_codes", []))
    skipped_unpaid = 0
    timezone = options["timezone"]

    def issue(code, severity, row, field, message):
        issues.append(
            {
                "code": code,
                "severity": severity,
                "row_number": row,
                "field": field,
                "message": message,
                "acknowledged": severity != "error" and code in ack,
            }
        )

    def value(row, field, required=False):
        column = columns.get(field)
        text = row["values"].get(column, "") if column else ""
        if column in row.get("formulas", []):
            raise ValueError("映射字段包含公式，请转为值后重新上传。")
        if required and not text:
            raise ValueError(f"{field} 缺失，请修正映射、补齐数据或排除此行。")
        return text

    def money(raw):
        amount = number(raw, options["decimal_separator"])
        factor = 10 ** options["currency_exponent"] if options["input_money_unit"] == "major" else 1
        minor = amount * factor
        if minor != minor.to_integral_value() or minor < 0 or minor > SAFE_INTEGER:
            raise ValueError("金额须非负且符合币种精度，不能自动舍入或溢出。")
        return int(minor)

    required = ["sku", "unit_cost"] if kind == "costs" else ["order_id", "paid_at", "quantity"]
    if kind == "orders":
        required += ["unit_price"] if options["amount_scope"] == "derived" else ["line_paid_minor"]
        if options["payment_state_mode"] == "mapped":
            required += ["payment_state"]
        if options["refund_mode"] == "provided":
            required += ["line_refund_minor"]
        if options["amount_scope"].startswith("order_"):
            required += ["allocation_weight"]
        if options["amount_scope"] == "order_with_shipping":
            required += ["shipping_minor"]
    for field in required:
        if field not in columns:
            issue("MAPPING_REQUIRED", "error", 0, field, f"请映射 {field}。")
    for field, column in columns.items():
        if column not in parsed["columns"]:
            issue("COLUMN_NOT_FOUND", "error", 0, field, f"所选列 {column[:100]} 不存在。")
    if not options["semantics_confirmed"]:
        issue("SEMANTICS_REQUIRED", "error", 0, "", "请确认币种、金额、支付状态、退款与成本口径。")
    for code in parsed["warnings"]:
        issue(code, "warning", 0, "", "工作簿包含隐藏行/工作表或合并单元格，请核实导入范围。")
    if excluded - {r["row_number"] for r in parsed["rows"]}:
        issue("INVALID_EXCLUSION", "error", 0, "", "排除行号不在当前工作表中，请重新确认。")
    start = end = cutoff = None
    if kind == "orders":
        try:
            start = timestamp(options["coverage_start"], timezone)
            end = timestamp(options["coverage_end_exclusive"], timezone)
            cutoff = timestamp(options["source_as_of"], timezone)
            if start >= end or end > cutoff:
                raise ValueError("覆盖开始须早于结束，截止时间不得早于覆盖结束。")
        except ValueError as exc:
            issue("COVERAGE_INVALID", "error", 0, "", str(exc))
        if not options["coverage_confirmed"]:
            issue("COVERAGE_REQUIRED", "error", 0, "", "必须明确确认完整提取的时间范围。")
        if options["refund_mode"] == "unknown":
            issue(
                "REFUND_UNKNOWN",
                "warning",
                0,
                "line_refund_minor",
                "退款未知：保留销售实付，但净销售额与净毛利不可用。",
            )
        if options["refund_scope"] == "order" and options["refund_mode"] == "provided":
            issue(
                "REFUND_ALLOCATED",
                "warning",
                0,
                "",
                "订单退款按明细实付分摊，商品级退款与毛利标记为估算。",
            )
    if any(i["severity"] == "error" and i["row_number"] == 0 for i in issues):
        return report(output, issues, len(parsed["rows"]), len(excluded), skipped_unpaid)
    seen_ids, seen_content, order_groups, states = {}, {}, defaultdict(list), defaultdict(set)
    for row in parsed["rows"]:
        index = row["row_number"]
        if index in excluded:
            continue
        try:
            for field in columns:
                value(row, field)  # Reject any mapped formula, even in optional fields.
            for field in ("order_id", "order_line_id", "sku"):
                text = value(row, field)
                if len(text) > 128:
                    raise ValueError(f"{field} 超过 128 字符。")
                if columns.get(field) in row.get("numeric", []):
                    if len(text.split(".")[0]) > 15:
                        raise ValueError("标识符以 Excel 数字存储且超过 15 位，请回源导出文本。")
                    issue(
                        "NUMERIC_IDENTIFIER",
                        "warning",
                        index,
                        field,
                        "标识符来自数字单元格，请确认前导零与原始精度。",
                    )
            currency = value(row, "currency") or options["currency"]
            if currency != options["currency"]:
                raise ValueError("币种与导入口径不一致，不允许混币种导入。")
            if kind == "costs":
                unit_cost = number(value(row, "unit_cost", True), options["decimal_separator"])
                if (
                    unit_cost < 0
                    or unit_cost > Decimal("99999999999999.999999")
                    or unit_cost.as_tuple().exponent < -6
                ):
                    raise ValueError("单位成本必须非负、最多 6 位小数且不超过 NUMERIC(20,6)。")
                beginning = timestamp(
                    value(row, "effective_from") or options["cost_effective_from"], timezone
                )
                end_value = value(row, "effective_to") or options["cost_effective_to"]
                ending = timestamp(end_value, timezone) if end_value else None
                if ending and beginning >= ending:
                    raise ValueError("成本生效起点必须早于终点。")
                if unit_cost == 0:
                    issue(
                        "ZERO_COST",
                        "warning",
                        index,
                        "unit_cost",
                        "单位成本为零，请确认不是缺失值。",
                    )
                output.append(
                    {
                        "sku": value(row, "sku", True),
                        "unit_cost": str(unit_cost),
                        "currency": currency,
                        "effective_from": beginning.isoformat(),
                        "effective_to": ending.isoformat() if ending else None,
                        "source_row_number": index,
                    }
                )
                continue
            order_id = value(row, "order_id", True)
            if order_id.strip().lower() in {"合计", "总计", "小计", "total", "subtotal"}:
                raise ValueError("疑似汇总行，请确认并排除，不能作为订单导入。")
            state = (
                "paid"
                if options["payment_state_mode"] == "confirmed_all_paid"
                else options["status_mapping"].get(value(row, "payment_state", True))
            )
            if not state:
                raise ValueError("订单状态未配置映射。")
            states[order_id].add(state)
            if state != "paid":
                skipped_unpaid += 1
                continue
            paid_at = timestamp(value(row, "paid_at", True), timezone)
            if not start <= paid_at < end or paid_at > cutoff:
                raise ValueError("支付时间不在已确认的半开覆盖区间内，或晚于截止时间。")
            quantity = number(value(row, "quantity", True))
            if quantity != int(quantity) or not 0 < quantity <= 2147483647:
                raise ValueError("购买数量必须为有效正整数。")
            paid = (
                money(value(row, "line_paid_minor", True))
                if options["amount_scope"] != "derived"
                else money(value(row, "unit_price", True)) * int(quantity)
                - money(value(row, "discount_minor") or "0")
            )
            if paid < 0 or paid > SAFE_INTEGER:
                raise ValueError("推导实付金额为负或超出安全范围。")
            refund = (
                money(value(row, "line_refund_minor", True))
                if options["refund_mode"] == "provided"
                else 0
                if options["refund_mode"] == "confirmed_none"
                else None
            )
            returned = value(row, "restocked_quantity")
            restocked = number(returned) if returned else 0 if refund == 0 else None
            if restocked is not None and (
                restocked != int(restocked) or not 0 <= restocked <= quantity
            ):
                raise ValueError("已回库数量必须是 0 到购买数量之间的整数。")
            external_id = value(row, "order_line_id") or None
            canonical = {field: value(row, field) for field in sorted(columns)}
            fingerprint = hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()
            if (
                external_id
                and (order_id, external_id) in seen_ids
                and seen_ids[(order_id, external_id)] != fingerprint
            ):
                issue(
                    "CONFLICTING_LINE_ID",
                    "error",
                    index,
                    "order_line_id",
                    "同订单明细编号对应冲突内容，请修复或排除此行。",
                )
            if fingerprint in seen_content:
                issue(
                    "DUPLICATE_ROW",
                    "warning",
                    index,
                    "",
                    f"与第 {seen_content[fingerprint]} 行内容相同，请确认保留或排除。",
                )
            seen_content[fingerprint] = index
            if external_id:
                seen_ids[(order_id, external_id)] = fingerprint
            sku = value(row, "sku") or None
            if not sku:
                issue(
                    "SKU_MISSING",
                    "warning",
                    index,
                    "sku",
                    "缺少 SKU，仅可用于销售汇总，无法匹配商品成本。",
                )
            if restocked is None and refund != 0:
                issue(
                    "RESTOCK_UNKNOWN",
                    "warning",
                    index,
                    "restocked_quantity",
                    "回库数量未知，后续成本不回转并标为估算。",
                )
            normalized = {
                "line_id": hashlib.sha256(f"{file_hash}:{index}".encode()).hexdigest(),
                "order_id": order_id,
                "order_line_id": external_id,
                "sku": sku,
                "product_name": value(row, "product_name") or sku or "未映射商品",
                "paid_at": paid_at.isoformat(),
                "quantity": int(quantity),
                "line_paid_minor": paid,
                "line_refund_minor": refund,
                "restocked_quantity": int(restocked) if restocked is not None else None,
                "currency": currency,
                "source_row_number": index,
                "unit_cost": None,
                "quality": {
                    "refund_allocation": "estimated"
                    if options["refund_scope"] == "order" and refund is not None
                    else "confirmed"
                },
            }
            if options["amount_scope"].startswith("order_"):
                normalized["_weight"] = str(
                    number(value(row, "allocation_weight", True), options["decimal_separator"])
                )
                normalized["_shipping"] = (
                    money(value(row, "shipping_minor", True))
                    if options["amount_scope"] == "order_with_shipping"
                    else 0
                )
            output.append(normalized)
            order_groups[order_id].append(normalized)
        except (ValueError, InvalidOperation) as exc:
            issue("INVALID_ROW", "error", index, "", str(exc)[:250])
    if kind == "costs":
        grouped = defaultdict(list)
        for row in output:
            grouped[row["sku"]].append(row)
        for group in grouped.values():
            ordered = sorted(group, key=lambda x: x["effective_from"])
            furthest = ""
            for row in ordered:
                if row["effective_from"] < furthest:
                    issue(
                        "COST_OVERLAP",
                        "error",
                        row["source_row_number"],
                        "effective_from",
                        "同 SKU 成本生效区间重叠。",
                    )
                furthest = max(furthest, row["effective_to"] or "9999")
    else:
        for group in order_groups.values():
            try:
                if (
                    len({r["paid_at"] for r in group}) != 1
                    or len(states[group[0]["order_id"]]) != 1
                ):
                    raise ValueError("同订单支付时间或支付状态冲突。")
                ids = [r["order_line_id"] or r["line_id"] for r in group]
                if options["amount_scope"].startswith("order_"):
                    totals = {r["line_paid_minor"] for r in group}
                    shipping = {r["_shipping"] for r in group}
                    if (
                        len(totals) != 1
                        or len(shipping) != 1
                        or next(iter(totals)) < next(iter(shipping))
                    ):
                        raise ValueError("订单总额/运费在明细行不一致或运费超过实付。")
                    parts = allocate(
                        next(iter(totals)) - next(iter(shipping)),
                        [Decimal(r["_weight"]) for r in group],
                        ids,
                    )
                    for r, part in zip(group, parts, strict=True):
                        r["line_paid_minor"] = part
                        r.pop("_weight", None)
                        r.pop("_shipping", None)
                if options["refund_scope"] == "order" and options["refund_mode"] == "provided":
                    refunds = {r["line_refund_minor"] for r in group}
                    if len(refunds) != 1:
                        raise ValueError("订单累计退款在各行不一致。")
                    total_refund = refunds.pop()
                    parts = (
                        allocate(total_refund, [Decimal(r["line_paid_minor"]) for r in group], ids)
                        if total_refund
                        else [0] * len(group)
                    )
                    for r, part in zip(group, parts, strict=True):
                        r["line_refund_minor"] = part
                for r in group:
                    if (
                        r["line_refund_minor"] is not None
                        and r["line_refund_minor"] > r["line_paid_minor"]
                    ):
                        issue(
                            "REFUND_EXCEEDS_PAID",
                            "error",
                            r["source_row_number"],
                            "line_refund_minor",
                            "累计退款超过商品实付。",
                        )
            except ValueError as exc:
                issue("ORDER_CONFLICT", "error", group[0]["source_row_number"], "", str(exc))
        cost_index = defaultdict(list)
        for cost in costs:
            cost_index[cost["sku"]].append(cost)
        cost_starts = {}
        for sku, group in cost_index.items():
            group.sort(key=lambda c: c["effective_from"])
            cost_starts[sku] = [c["effective_from"] for c in group]
        for r in output:
            # Published cost versions have already rejected overlapping intervals.
            position = bisect_right(cost_starts.get(r["sku"], []), r["paid_at"]) - 1
            matched = cost_index[r["sku"]][position] if position >= 0 else None
            if (
                matched
                and matched["currency"] == r["currency"]
                and (not matched["effective_to"] or r["paid_at"] < matched["effective_to"])
            ):
                r["unit_cost"] = matched["unit_cost"]
            else:
                issue(
                    "COST_MISSING",
                    "warning",
                    r["source_row_number"],
                    "unit_cost",
                    "未匹配唯一且同币种的有效成本；不按零成本计算。",
                )
        if sum(r["line_paid_minor"] for r in output) > SAFE_INTEGER:
            issue("TOTAL_OVERFLOW", "error", 0, "", "总金额超过前端安全整数范围，请拆分数据。")
    if not output:
        issue("EMPTY_RESULT", "error", 0, "", "没有可发布的数据行。")
    return report(output, issues, len(parsed["rows"]), len(excluded), skipped_unpaid)


def report(rows, issues, total, excluded, unpaid):
    counts = Counter(i["code"] for i in issues)
    summary = {
        "source_rows": total,
        "included_rows": len(rows),
        "excluded_rows": excluded,
        "unpaid_rows": unpaid,
        "errors": sum(i["severity"] == "error" for i in issues),
        "unacknowledged": sum(i["severity"] != "error" and not i["acknowledged"] for i in issues),
        "issue_counts": dict(counts),
        "warning_codes": sorted({i["code"] for i in issues if i["severity"] != "error"}),
        "cost_matched_rows": sum(r.get("unit_cost") is not None for r in rows),
    }
    return {"rows": rows, "issues": issues, "summary": summary}
