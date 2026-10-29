"""Deterministic synthetic order data with injected, labelled business changes."""

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
    for m in mutations:
        if m["type"] == "negative_margin":
            cost_ratio[m["sku"]] = m.get("ratio", 1.3)
    zone = ZoneInfo(TIMEZONE)
    rows, order_number = [], 0
    for offset in range(days):
        day = start + timedelta(days=offset)
        current = day >= current_start
        for sku in skus:
            count = weight[sku] * rnd.uniform(0.7, 1.3)
            for m in mutations if current else []:
                if m["type"] == "sales_drop" and m["sku"] == sku:
                    count *= m.get("factor", 0.3)
                if m["type"] == "sales_surge" and m["sku"] == sku:
                    count *= m.get("factor", 3)
                if m["type"] == "concentration" and sku in m["skus"]:
                    count *= m.get("factor", 8)
                if m["type"] == "daily_outlier" and m["date"] == day.isoformat():
                    count *= m.get("factor", 6)
            for _ in range(int(count + rnd.random())):
                order_number += 1
                quantity = rnd.randint(1, 3)
                paid = quantity * price[sku]
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
                        (Decimal(price[sku]) * Decimal(str(cost_ratio[sku])) / 100).quantize(
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
                        "product_name": "示例商品 " + sku[-2:],
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
