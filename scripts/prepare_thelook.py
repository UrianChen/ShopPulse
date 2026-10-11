"""Prepare a pinned public TheLook snapshot for the README demo (stdlib only).

Source data are synthetic. Payment and refund mappings below are DEMO assumptions,
not payment/refund records from the source. See README for scope and limitations.
"""

import csv
import hashlib
import json
from collections import Counter
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
COMMIT = "bb74707d5ab31c35795e017d2dc7f98895efb0af"
BASE = f"https://raw.githubusercontent.com/marcelFRO/ecommerce-analytics/{COMMIT}/data/raw/"
HASHES = {
    "orders": "6b710889a08cfad310e7b5939618715fb238280659c4e210fc23d925ca86175b",
    "order_items": "fe86c46cb0b947cbcedc8abc066c4458b0b577de8d72e116d965476d3b143355",
    "products": "66b85a3483bc2c90e1a0229817a700164a83b80b9525c76b330fadfcb1c800e6",
}
START, END = "2023-11-13", "2024-01-08"
AS_OF = "2024-01-28T00:00:00+00:00"


def prepare():
    raw = ROOT / ".cache/thelook-demo/raw"
    out = ROOT / "samples/thelook"
    raw.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    tables = {}
    for name, expected in HASHES.items():
        path = raw / f"{name}.csv"
        if not path.exists():
            with urlopen(BASE + path.name, timeout=60) as response:
                path.write_bytes(response.read())
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Source checksum mismatch: {name}")
        with path.open(encoding="utf-8-sig", newline="") as source:
            tables[name] = list(csv.DictReader(source))
        assert all(
            None not in r and all(v is not None for v in r.values())
            for r in tables[name]
        )

    orders = {r["order_id"]: r for r in tables["orders"]}
    products = {r["id"]: r for r in tables["products"]}
    assert len(orders) == len(tables["orders"])
    assert len(products) == len(tables["products"])
    assert len({r["id"] for r in tables["order_items"]}) == len(tables["order_items"])
    eligible = {
        k: r
        for k, r in orders.items()
        if START <= r["created_at"][:10] < END
        and r["status"] in {"Complete", "Shipped", "Returned"}
    }
    lines, used, counts = [], set(), Counter()
    for item in tables["order_items"]:
        assert item["order_id"] in orders and item["product_id"] in products
        if item["order_id"] not in eligible:
            continue
        order = eligible[item["order_id"]]
        assert item["status"] == order["status"]
        product = products[item["product_id"]]
        returned = item["status"] == "Returned"
        if returned:
            assert item["returned_at"] and datetime.fromisoformat(
                item["returned_at"]
            ) < datetime.fromisoformat(AS_OF)
        paid = Decimal(item["sale_price"]).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        lines.append(
            {
                "order_id": order["order_id"],
                "order_line_id": item["id"],
                "sku": "TL-" + product["id"],
                "product_name": product["name"],
                "paid_at": datetime.fromisoformat(order["created_at"]).isoformat(),
                "quantity": 1,
                "line_paid": str(paid),
                "line_refund": str(paid) if returned else "0.00",
                "restocked_quantity": "" if returned else "0",
            }
        )
        used.add(product["id"])
        counts[order["order_id"]] += 1
    assert all(counts[k] == int(r["num_of_item"]) for k, r in eligible.items()), (
        "Incomplete order"
    )
    lines.sort(
        key=lambda r: (r["paid_at"], int(r["order_id"]), int(r["order_line_id"]))
    )
    costs = [
        {
            "sku": "TL-" + k,
            "unit_cost": str(
                Decimal(products[k]["cost"]).quantize(
                    Decimal("0.000001"), rounding=ROUND_HALF_UP
                )
            ),
            "currency": "USD",
            "effective_from": START + "T00:00:00+00:00",
            "effective_to": "",
        }
        for k in sorted(used, key=int)
    ]
    for name, rows in (("orders", lines), ("costs", costs)):
        with (out / f"{name}.csv").open(
            "w", encoding="utf-8-sig", newline=""
        ) as target:
            writer = csv.DictWriter(target, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    current = [r for r in lines if "2024-01-01" <= r["paid_at"][:10] < END]
    cost_by_sku = {r["sku"]: Decimal(r["unit_cost"]) for r in costs}
    gross = sum(Decimal(r["line_paid"]) for r in current)
    refunds = sum(Decimal(r["line_refund"]) for r in current)
    cogs = sum(
        cost_by_sku[r["sku"]].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        for r in current
    )
    manifest = {
        "dataset": "Google TheLook eCommerce (synthetic)",
        "mirror_commit": COMMIT,
        "source_urls": {n: BASE + n + ".csv" for n in HASHES},
        "source_sha256": HASHES,
        "coverage_start": START,
        "coverage_end_exclusive": END,
        "source_as_of_demo": AS_OF,
        "timezone": "UTC",
        "currency_demo": "USD",
        "rows": len(lines),
        "orders": len(eligible),
        "skus": len(costs),
        "returned_lines": sum(Decimal(r["line_refund"]) > 0 for r in lines),
        "included_order_statuses": dict(
            Counter(r["status"] for r in eligible.values())
        ),
        "assumptions": [
            "Complete/Shipped/Returned are treated as paid; Processing/Cancelled excluded.",
            "orders.created_at is used as a surrogate paid_at; each item has quantity one.",
            "Returned is treated as fully refunded; other included statuses have zero refunds.",
            "Return restocking is unknown; costs are not reversed and margin is estimated.",
            "USD and source_as_of are demo conventions, not verified source fields.",
            "Static product costs apply throughout the selected period; SKU is TL-product_id.",
            "Prices rounded HALF_UP to cents; costs to six decimals.",
        ],
        "weekly_independent_control": {
            "start": "2024-01-01",
            "end_exclusive": END,
            "paid_orders": len({r["order_id"] for r in current}),
            "paid_units": len(current),
            "gross_sales": str(gross),
            "refund_amount": str(refunds),
            "net_sales": str(gross - refunds),
            "net_cogs_estimated": str(cogs),
            "gross_profit_estimated": str(gross - refunds - cogs),
        },
        "output_sha256": {
            n: hashlib.sha256((out / n).read_bytes()).hexdigest()
            for n in ("orders.csv", "costs.csv")
        },
        "license_note": (
            "Public mirror; no independent dataset redistribution license verified. "
            "Project code license does not license source data."
        ),
    }
    (out / "provenance.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                k: manifest[k]
                for k in (
                    "rows",
                    "orders",
                    "skus",
                    "returned_lines",
                    "weekly_independent_control",
                )
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    prepare()
