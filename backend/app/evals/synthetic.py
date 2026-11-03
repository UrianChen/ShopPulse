"""Deterministic synthetic order data with injected, labelled business changes.

Mutations (``current`` means the report period, the last ``period_days`` days):

- ``refund_spike`` {sku, rate}: share of the SKU's current orders fully refunded.
- ``sales_drop`` / ``sales_surge`` {sku, factor}: current order volume of one SKU.
- ``concentration`` {skus, factor}: current order volume of several SKUs.
- ``daily_outlier`` {date, factor}: order volume of every SKU on one day.
- ``negative_margin`` {sku, ratio}: cost ratio of a SKU in every period.
- ``missing_cost`` {sku}: the SKU has no cost records.
- ``price`` {factor, sku?}: current unit price of one SKU or of all SKUs (order count unchanged).
- ``basket`` {min, max}: units per order line in the current period.
- ``cost_ratio`` {sku, ratio}: cost ratio of a SKU in every period (product-mix setups).
- ``cost_increase`` {sku, ratio}: cost ratio of a SKU in the current period only.
- ``weight`` {sku, value}: base daily order rate of a SKU (small-sample setups).
- ``scale`` {factor}: base daily order rate of every SKU (larger samples for trend setups).
- ``trend`` {weekly}: order volume of every SKU multiplied by ``weekly`` per elapsed week.
- ``name`` {sku, text}: product name override (prompt-injection setups).

Mutations that do not apply never consume random numbers, so adding a mutation type keeps the
data of every existing case byte-identical.
"""

import random
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from app.ingestion.schema import ImportConfig

TIMEZONE = "Asia/Shanghai"


def snapshot(start, end):
    config = ImportConfig().model_dump(mode="json")
    config["options"].update(
        timezone=TIMEZONE,
        currency="CNY",
        currency_exponent=2,
        semantics_confirmed=True,
        coverage_confirmed=True,
        payment_state_mode="confirmed_all_paid",
        refund_mode="provided",
        coverage_start=f"{start.isoformat()}T00:00:00+08:00",
        coverage_end_exclusive=f"{end.isoformat()}T00:00:00+08:00",
        source_as_of=f"{(end + timedelta(days=2)).isoformat()}T00:00:00+08:00",
    )
    return {"config": config, "resolutions": {}}


def _of(mutations, kind, sku=None):
    return next(
        (m for m in mutations if m["type"] == kind and (sku is None or m.get("sku") == sku)), None
    )


def generate(spec):
    """Return {"rows", "snapshot", "query"} for an evaluation case spec."""
    rnd = random.Random(spec.get("seed", 1))
    n_skus = spec.get("skus", 16)
    days = spec.get("days", 56)
    period = spec.get("period_days", 7)
    end = date.fromisoformat(spec.get("end", "2026-10-05"))
    start = end - timedelta(days=days)
    current_start = end - timedelta(days=period)
    skus = [f"SP-{chr(65 + i // 26)}{chr(65 + i % 26)}" for i in range(n_skus)]
    price = {s: rnd.randint(30, 300) * 100 for s in skus}
    cost_ratio = {s: rnd.uniform(0.35, 0.6) for s in skus}
    weight = {s: rnd.uniform(0.6, 3.0) for s in skus}
    mutations = spec.get("mutations", [])
    names = {s: "示例商品 " + s[-2:] for s in skus}
    for m in mutations:
        if m["type"] in {"negative_margin", "cost_ratio"}:
            cost_ratio[m["sku"]] = m.get("ratio", 1.3)
        if m["type"] == "weight":
            weight[m["sku"]] = m["value"]
        if m["type"] == "scale":
            weight = {s: w * m["factor"] for s, w in weight.items()}
        if m["type"] == "name":
            names[m["sku"]] = m["text"]
    trend = _of(mutations, "trend")
    basket = _of(mutations, "basket")
    zone = ZoneInfo(TIMEZONE)
    rows, order_number = [], 0
    for offset in range(days):
        day = start + timedelta(days=offset)
        current = day >= current_start
        for sku in skus:
            count = weight[sku] * rnd.uniform(0.7, 1.3)
            if trend:
                count *= trend["weekly"] ** (offset // 7)
            for m in mutations if current else []:
                if m["type"] == "sales_drop" and m["sku"] == sku:
                    count *= m.get("factor", 0.3)
                if m["type"] == "sales_surge" and m["sku"] == sku:
                    count *= m.get("factor", 3)
                if m["type"] == "concentration" and sku in m["skus"]:
                    count *= m.get("factor", 8)
                if m["type"] == "daily_outlier" and m["date"] == day.isoformat():
                    count *= m.get("factor", 6)
            unit_price = price[sku]
            ratio = cost_ratio[sku]
            if current:
                change = next(
                    (m for m in mutations if m["type"] == "price" and m.get("sku") in (None, sku)),
                    None,
                )
                if change:
                    unit_price = int(Decimal(unit_price) * Decimal(str(change["factor"])))
                increase = _of(mutations, "cost_increase", sku)
                if increase:
                    ratio = increase["ratio"]
            for _ in range(int(count + rnd.random())):
                order_number += 1
                if current and basket:
                    quantity = rnd.randint(basket["min"], basket["max"])
                else:
                    quantity = rnd.randint(1, 3)
                paid = quantity * unit_price
                refund, restocked = 0, 0
                spike = next(
                    (
                        m
                        for m in mutations
                        if current and m["type"] == "refund_spike" and m["sku"] == sku
                    ),
                    None,
                )
                if rnd.random() < (spike["rate"] if spike else 0.03):
                    refund, restocked = paid, quantity
                missing = any(m["type"] == "missing_cost" and m["sku"] == sku for m in mutations)
                unit_cost = (
                    None
                    if missing
                    else str(
                        (Decimal(unit_price) * Decimal(str(ratio)) / 100).quantize(
                            Decimal("0.01"), rounding=ROUND_HALF_UP
                        )
                    )
                )
                paid_at = datetime(
                    day.year,
                    day.month,
                    day.day,
                    rnd.randint(8, 22),
                    rnd.randint(0, 59),
                    tzinfo=zone,
                )
                rows.append(
                    {
                        "order_id": f"E{order_number:06d}",
                        "sku": sku,
                        "product_name": names[sku],
                        "paid_at": paid_at.isoformat(),
                        "quantity": quantity,
                        "line_paid_minor": paid,
                        "line_refund_minor": refund,
                        "restocked_quantity": restocked,
                        "unit_cost": unit_cost,
                        "quality": {},
                    }
                )
    query = {
        "dataset_id": spec.get("dataset_id", "00000000-0000-0000-0000-00000000e7a1"),
        "start": current_start.isoformat(),
        "end_exclusive": end.isoformat(),
        "comparison": "previous",
        "skus": [],
        "granularity": "day",
    }
    return {"rows": rows, "snapshot": snapshot(start, end), "query": query}
