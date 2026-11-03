"""Authoritative money stays integer/Decimal; Pandas only indexes and groups rows."""

from collections import defaultdict
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal, localcontext
from zoneinfo import ZoneInfo

import pandas as pd

from app.ingestion.normalize import timestamp
from app.metrics.schema import DEFINITION_VERSION, ENGINE_VERSION, MetricQuery

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


def wire(value):
    if isinstance(value, Decimal):
        if value.as_tuple().exponent < -12:
            value = value.quantize(Decimal("0.000000000001"), rounding=ROUND_HALF_UP)
        return format(value, "f")
    if isinstance(value, dict):
        return {k: wire(v) for k, v in value.items()}
    if isinstance(value, list):
        return [wire(v) for v in value]
    return value


def aggregate(rows, options, complete):
    count = len(rows)
    gross = sum(int(r["line_paid_minor"]) for r in rows)
    orders = len({r["order_id"] for r in rows})
    refund_known = not count or (
        options["refund_mode"] != "unknown"
        and all(r["line_refund_minor"] is not None for r in rows)
    )
    refunded = sum(int(r["line_refund_minor"]) for r in rows) if refund_known else None
    net = gross - refunded if refund_known else None
    matched = [r for r in rows if r["unit_cost"] is not None]
    restock_estimated = [
        r for r in matched if r["restocked_quantity"] is None and r["line_refund_minor"] != 0
    ]
    refund_estimated = any(
        r["quality"].get("refund_allocation") == "estimated" and r["line_refund_minor"] != 0
        for r in rows
    )
    factor = Decimal(10) ** options["currency_exponent"]
    cogs = sum(
        int(
            (
                Decimal(str(r["unit_cost"]))
                * (int(r["quantity"]) - int(r["restocked_quantity"] or 0))
                * factor
            ).quantize(Decimal(1), rounding=ROUND_HALF_UP)
        )
        for r in matched
    )
    full_cost = len(matched) == count
    profit = net - cogs if full_cost and net is not None else None
    raw = {
        "gross_sales": gross,
        "refund_amount": refunded,
        "net_sales": net,
        "paid_orders": orders,
        "paid_units": sum(int(r["quantity"]) for r in rows),
        "aov": Decimal(net) / orders if orders and net is not None else None,
        "gross_aov": Decimal(gross) / orders if orders else None,
        "net_cogs": cogs if full_cost else None,
        "gross_profit": profit,
        "gross_margin": Decimal(profit) / net if profit is not None and net > 0 else None,
        "refund_amount_rate": Decimal(refunded) / gross if refund_known and gross > 0 else None,
        "refunded_order_rate": Decimal(
            len(
                {
                    r["order_id"]
                    for r in rows
                    if r["line_refund_minor"] and r["line_refund_minor"] > 0
                }
            )
        )
        / orders
        if refund_known and orders
        else None,
        "cost_line_coverage": Decimal(len(matched)) / count if count else None,
        "cost_amount_coverage": Decimal(sum(int(r["line_paid_minor"]) for r in matched)) / gross
        if gross
        else None,
    }
    metrics = {}
    for key, value in raw.items():
        reason = None
        if not complete and not rows:
            value, reason = None, "INCOMPLETE_COVERAGE"
        elif value is None:
            if (
                key
                in {
                    "refund_amount",
                    "net_sales",
                    "aov",
                    "gross_profit",
                    "gross_margin",
                    "refund_amount_rate",
                    "refunded_order_rate",
                }
                and not refund_known
            ):
                reason = "REFUND_UNKNOWN"
            elif key in {"net_cogs", "gross_profit", "gross_margin"} and not full_cost:
                reason = "COST_MISSING"
            else:
                reason = "ZERO_DENOMINATOR"
        estimated = (
            not complete
            or (bool(restock_estimated) and key in {"net_cogs", "gross_profit", "gross_margin"})
            or (
                refund_estimated
                and key
                in {
                    "refund_amount",
                    "net_sales",
                    "aov",
                    "gross_profit",
                    "gross_margin",
                    "refund_amount_rate",
                    "refunded_order_rate",
                }
            )
        )
        metrics[key] = {
            "value": Decimal(value) if value is not None else None,
            "unit": UNITS[key],
            "quality": "unavailable"
            if value is None
            else "estimated"
            if estimated
            else "confirmed",
            "unavailable_reason": reason,
        }
    missing = [r for r in rows if r["unit_cost"] is None]
    return {
        "metrics": metrics,
        "row_count": count,
        "coverage_complete": complete,
        "quality": {
            "missing_cost_rows": len(missing),
            "missing_cost_skus": len({r["sku"] for r in missing}),
            "missing_cost_paid_minor": str(sum(int(r["line_paid_minor"]) for r in missing)),
            "estimated_restock_rows": len(restock_estimated),
            "estimated_restock_paid_minor": str(
                sum(int(r["line_paid_minor"]) for r in restock_estimated)
            ),
            "refund_allocated": refund_estimated,
        },
    }


def comparison(current, previous):
    results = {}
    for key, a in current["metrics"].items():
        b = previous["metrics"][key]
        x, y = a["value"], b["value"]
        item = {
            "delta": None,
            "change_rate": None,
            "delta_pp": None,
            "state": "unavailable",
            "quality": "unavailable",
        }
        if not current["coverage_complete"] or not previous["coverage_complete"]:
            item["state"] = "incomplete_coverage"
        elif x is not None and y is not None:
            item.update(
                delta=x - y,
                quality="estimated" if "estimated" in {a["quality"], b["quality"]} else "confirmed",
            )
            if a["unit"] == "ratio":
                item.update(delta_pp=(x - y) * 100, state="comparable")
            elif x < 0 <= y:
                item["state"] = "turned_negative"
            elif y < 0 <= x:
                item["state"] = "turned_positive"
            elif y < 0:
                item["state"] = "negative_baseline"
            elif y == 0:
                item["state"] = "both_zero" if x == 0 else "new"
            else:
                item.update(change_rate=(x - y) / y, state="comparable")
        results[key] = item
    return results


def orders_of(product):
    """Per-SKU order counts so report tools can flag small samples."""
    previous = product["previous"]
    return {
        "orders_current": product["current"]["metrics"]["paid_orders"]["value"],
        "orders_previous": previous["metrics"]["paid_orders"]["value"] if previous else None,
    }


def _unavailable(metric, reason):
    return {"metric": metric, "available": False, "reason": reason, "items": []}


def shift_share(products, current, previous, metric, numerator, denominator):
    """Split a ratio change into product-mix and per-product rate effects (percentage points).

    R = sum(w_i * r_i) with w_i the product share of the denominator and r_i its own ratio, so
    R1 - R0 = sum((w1 - w0) * r0) + sum(w1 * (r1 - r0)) exactly. A product missing from one period
    uses its other-period ratio as reference. Products whose denominator is zero while the
    numerator is not (for example fully refunded lines with cost) cannot be weighted; their effect
    is reported as ``other_pp`` so the three parts always add up to the total change.
    """
    if previous is None:
        return _unavailable(metric, "NO_COMPARISON")
    if not current["coverage_complete"] or not previous["coverage_complete"]:
        return _unavailable(metric, "INCOMPLETE_COVERAGE")
    totals = []
    for period in (current, previous):
        n, d = (period["metrics"][k]["value"] for k in (numerator, denominator))
        if n is None or d is None or period["metrics"][metric]["value"] is None:
            return _unavailable(metric, "UNAVAILABLE_VALUE")
        if d <= 0:
            return _unavailable(metric, "NON_POSITIVE_BASE")
        totals.append(Decimal(d))
    d1_total, d0_total = totals
    estimated = any(
        p["metrics"][k]["quality"] == "estimated"
        for p in (current, previous)
        for k in (metric, numerator, denominator)
    )
    items, mix_total, rate_total = [], Decimal(0), Decimal(0)
    for p in products:
        values = []
        for period in (p["current"], p["previous"]):
            if period is None:
                values += [0, 0]
                continue
            n, d = period["metrics"][numerator]["value"], period["metrics"][denominator]["value"]
            if n is None or d is None:
                return _unavailable(metric, "UNAVAILABLE_VALUE")
            if d < 0:
                return _unavailable(metric, "NEGATIVE_VALUES")
            values += [n, d]
        n1, d1, n0, d0 = values
        r1 = Decimal(n1) / d1 if d1 > 0 else None
        r0 = Decimal(n0) / d0 if d0 > 0 else None
        if r1 is None and r0 is None:
            continue
        reference0 = r1 if r0 is None else r0
        reference1 = reference0 if r1 is None else r1
        w1, w0 = Decimal(d1) / d1_total, Decimal(d0) / d0_total
        mix = (w1 - w0) * reference0 * 100
        rate = w1 * (reference1 - reference0) * 100
        mix_total += mix
        rate_total += rate
        items.append(
            {
                "sku": p["sku"],
                "product_name": p["product_name"],
                "mix_effect_pp": mix,
                "rate_effect_pp": rate,
                "total_effect_pp": mix + rate,
                "current_share": w1,
                "previous_share": w0,
                "current_rate": r1,
                "previous_rate": r0,
                **orders_of(p),
            }
        )
    delta = (current["metrics"][metric]["value"] - previous["metrics"][metric]["value"]) * 100
    items.sort(key=lambda item: (-abs(item["total_effect_pp"]), item["sku"] or ""))
    return {
        "metric": metric,
        "available": True,
        "reason": None,
        "quality": "estimated" if estimated else "confirmed",
        "delta_pp": delta,
        "mix_effect_pp": mix_total,
        "rate_effect_pp": rate_total,
        "other_pp": delta - mix_total - rate_total,
        "items": items[:10],
    }


def aov_factors(current, previous):
    """AOV = price per unit x units per order; change = price effect + basket effect (exact)."""
    if previous is None:
        return _unavailable("aov", "NO_COMPARISON")
    if not current["coverage_complete"] or not previous["coverage_complete"]:
        return _unavailable("aov", "INCOMPLETE_COVERAGE")
    factors, qualities = [], set()
    for period in (current, previous):
        m = period["metrics"]
        net, units, orders = (m[k]["value"] for k in ("net_sales", "paid_units", "paid_orders"))
        if net is None or m["aov"]["value"] is None:
            return _unavailable("aov", "UNAVAILABLE_VALUE")
        if not units or not orders:
            return _unavailable("aov", "NON_POSITIVE_BASE")
        factors.append((Decimal(net) / units, Decimal(units) / orders))
        qualities.add(m["aov"]["quality"])
    (p1, u1), (p0, u0) = factors
    return {
        "metric": "aov",
        "available": True,
        "reason": None,
        "quality": "estimated" if "estimated" in qualities else "confirmed",
        "delta_minor": p1 * u1 - p0 * u0,
        "price_effect_minor": (p1 - p0) * u0,
        "basket_effect_minor": p1 * (u1 - u0),
        "units_per_order": {"current": u1, "previous": u0},
        "items": [],
    }


HISTORY_KEYS = (
    "net_sales",
    "paid_orders",
    "paid_units",
    "aov",
    "gross_profit",
    "gross_margin",
    "refund_amount",
    "refund_amount_rate",
)


def history(rows, snapshot, windows):
    with localcontext() as context:
        context.prec = 70
        return wire(_history(rows, snapshot, windows))


def _history(rows, snapshot, windows):
    """Store-level aggregates for consecutive earlier windows, frozen into the report context."""
    options = snapshot["config"]["options"]
    zone = options["timezone"]
    coverage_start = timestamp(options["coverage_start"], zone)
    coverage_end = timestamp(options["coverage_end_exclusive"], zone)
    records = []
    for original in rows:
        r = dict(original)
        r["paid_at"] = timestamp(str(r["paid_at"]), zone)
        records.append(r)
    result = []
    for start, end in windows:
        a, b = timestamp(start, zone), timestamp(end, zone)
        complete = bool(options["coverage_confirmed"] and coverage_start <= a and b <= coverage_end)
        data = aggregate([r for r in records if a <= r["paid_at"] < b], options, complete)
        result.append(
            {
                "start": start,
                "end_exclusive": end,
                "coverage_complete": complete,
                "metrics": {k: data["metrics"][k] for k in HISTORY_KEYS},
            }
        )
    return {"windows": result}


def calculate(rows, snapshot, query):
    with localcontext() as context:
        context.prec = 70
        return wire(_calculate(rows, snapshot, MetricQuery.model_validate(query)))


def _calculate(rows, snapshot, query):
    options = snapshot["config"]["options"]
    zone = options["timezone"]
    coverage_start = timestamp(options["coverage_start"], zone)
    coverage_end = timestamp(options["coverage_end_exclusive"], zone)

    def bounds(start, end):
        return timestamp(start.isoformat(), zone), timestamp(end.isoformat(), zone)

    def complete(start, end):
        a, b = bounds(start, end)
        return bool(options["coverage_confirmed"] and coverage_start <= a and b <= coverage_end)

    records = []
    for original in rows:
        if query.skus and original["sku"] not in query.skus:
            continue
        r = dict(original)
        r["paid_at"] = timestamp(str(r["paid_at"]), zone)
        r["local_date"] = r["paid_at"].astimezone(ZoneInfo(zone)).date()
        r["group_key"] = "sku:" + r["sku"] if r["sku"] is not None else "unmapped"
        records.append(r)
    # Object dtype prevents Pandas from coercing nullable money to binary floating point.
    frame = pd.DataFrame(records, dtype=object)

    def select_period(start, end):
        if frame.empty:
            return []
        a, b = bounds(start, end)
        return [
            records[int(i)] for i in frame.index[(frame["paid_at"] >= a) & (frame["paid_at"] < b)]
        ]

    current_rows = select_period(query.start, query.end_exclusive)
    previous_rows = (
        select_period(query.compare_start, query.compare_end_exclusive)
        if query.compare_start
        else []
    )
    current_complete = complete(query.start, query.end_exclusive)
    previous_complete = (
        complete(query.compare_start, query.compare_end_exclusive) if query.compare_start else False
    )
    current = aggregate(current_rows, options, current_complete)
    matched = aggregate(
        [r for r in current_rows if r["unit_cost"] is not None], options, current_complete
    )
    previous = aggregate(previous_rows, options, previous_complete) if query.compare_start else None
    changes = comparison(current, previous) if previous else None
    periods = {
        "current": [query.start.isoformat(), query.end_exclusive.isoformat()],
        "previous": [query.compare_start.isoformat(), query.compare_end_exclusive.isoformat()]
        if previous
        else None,
    }
    buckets = defaultdict(list)
    for r in current_rows:
        bucket = (
            r["local_date"]
            if query.granularity == "day"
            else max(query.start, r["local_date"] - timedelta(days=r["local_date"].weekday()))
        )
        buckets[bucket].append(r)
    trend = []
    cursor = query.start
    while cursor < query.end_exclusive:
        end = min(
            query.end_exclusive,
            cursor + timedelta(days=1 if query.granularity == "day" else 7 - cursor.weekday()),
        )
        point = aggregate(buckets[cursor], options, complete(cursor, end))
        trend.append({"start": cursor.isoformat(), "end_exclusive": end.isoformat(), **point})
        cursor = end

    def groups(values):
        if not values:
            return {}
        data = pd.DataFrame(values, dtype=object)
        return {
            str(k): [values[int(i)] for i in indices]
            for k, indices in data.groupby("group_key", sort=True).indices.items()
        }

    cg, pg = groups(current_rows), groups(previous_rows)
    products = []
    for key in sorted(cg.keys() | pg.keys()):
        cr, pr = cg.get(key, []), pg.get(key, [])
        a = aggregate(cr, options, current_complete)
        b = aggregate(pr, options, previous_complete) if previous else None
        change = comparison(a, b) if b else None
        sample = (cr or pr)[0]
        products.append(
            {
                "group_key": key,
                "sku": sample["sku"],
                "product_name": sample["product_name"],
                "current": a,
                "previous": b,
                "comparison": change,
                "sales_contribution_minor": change["net_sales"]["delta"] if change else None,
            }
        )
    contributions = [p for p in products if p["sales_contribution_minor"] is not None]
    contribution_valid = (
        previous is not None
        and changes["net_sales"]["delta"] is not None
        and len(contributions) == len(products)
    )
    contributions.sort(key=lambda p: (p["sales_contribution_minor"], p["group_key"]))

    def contribution_item(p):
        return {
            **{k: p[k] for k in ("sku", "product_name", "sales_contribution_minor")},
            **orders_of(p),
        }

    effects = None
    if contribution_valid and previous["metrics"]["paid_orders"]["value"] > 0:
        order_effect = (
            current["metrics"]["paid_orders"]["value"] - previous["metrics"]["paid_orders"]["value"]
        ) * previous["metrics"]["aov"]["value"]
        effects = {
            "order_effect_minor": order_effect,
            "aov_effect_minor": changes["net_sales"]["delta"] - order_effect,
        }
    return {
        "result": {
            "schema_version": "1.0",
            "engine_version": ENGINE_VERSION,
            "metric_definition_version": DEFINITION_VERSION,
            "dataset_id": str(query.dataset_id),
            "timezone": zone,
            "currency": options["currency"],
            "currency_exponent": options["currency_exponent"],
            "source_as_of": options["source_as_of"],
            "query": query.model_dump(mode="json"),
            "periods": periods,
            "current": current,
            "previous": previous,
            "comparison": changes,
            "matched_cost_subset": matched,
            "trend": trend,
            "product_count": len(products),
            "contributions": {
                "available": contribution_valid,
                "total_minor": sum(p["sales_contribution_minor"] for p in contributions)
                if contribution_valid
                else None,
                "gainers": [
                    contribution_item(p)
                    for p in reversed(contributions)
                    if p["sales_contribution_minor"] > 0
                ][:5]
                if contribution_valid
                else [],
                "decliners": [
                    contribution_item(p) for p in contributions if p["sales_contribution_minor"] < 0
                ][:5]
                if contribution_valid
                else [],
                "effects": effects,
            },
            "decompositions": {
                "gross_margin": shift_share(
                    products, current, previous, "gross_margin", "gross_profit", "net_sales"
                ),
                "refund_amount_rate": shift_share(
                    products,
                    current,
                    previous,
                    "refund_amount_rate",
                    "refund_amount",
                    "gross_sales",
                ),
                "aov": aov_factors(current, previous),
            },
            "excluded_rows": len(snapshot.get("resolutions", {}).get("excluded_rows", [])),
            "warnings": [
                code
                for condition, code in [
                    (not current_complete, "INCOMPLETE_COVERAGE"),
                    (previous is not None and not previous_complete, "COMPARISON_INCOMPLETE"),
                    (current["quality"]["missing_cost_rows"] > 0, "COST_MISSING"),
                    (current["quality"]["estimated_restock_rows"] > 0, "RESTOCK_ESTIMATED"),
                    (
                        current["metrics"]["net_sales"]["value"] is None
                        and options["refund_mode"] == "unknown",
                        "REFUND_UNKNOWN",
                    ),
                    (current["quality"]["refund_allocated"], "REFUND_ALLOCATED"),
                    (
                        0 < current["metrics"]["paid_orders"]["value"] < 20
                        if current["metrics"]["paid_orders"]["value"] is not None
                        else False,
                        "SMALL_SAMPLE",
                    ),
                ]
                if condition
            ],
        },
        "products": products,
    }
