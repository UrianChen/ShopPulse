import copy
import csv
import io
import json
import random
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.db.models import DatasetVersion, Job, MetricProduct, MetricSnapshot, Workspace, now
from app.jobs.queue import claim
from app.jobs.worker import run_one
from app.metrics.engine import calculate, comparison
from app.metrics.schema import MetricQuery, MetricValue
from app.metrics.service import commit_result
from tests.test_ingestion import (
    SAMPLES,
    config,
    create_draft,
    normalize_orders,
    publish,
    validate,
)


def query(**kwargs):
    return MetricQuery(
        dataset_id=uuid.UUID(int=1), start="2026-09-28", end_exclusive="2026-10-05", **kwargs
    ).model_dump(mode="json")


def compute(rows=None, cfg=None, q=None):
    return calculate(
        normalize_orders()["rows"] if rows is None else rows,
        {"config": cfg or config(), "resolutions": {}},
        q or query(),
    )


def val(result, key, period="current"):
    return result["result"][period]["metrics"][key]["value"]


def test_independent_golden_metrics_and_unrounded_comparison():
    result = compute()
    expected = json.loads((SAMPLES / "expected_metrics.json").read_text())
    for period in ("current", "previous"):
        for metric in result["result"][period]["metrics"].values():
            MetricValue.model_validate(metric)
        for key, number in expected[period].items():
            assert Decimal(val(result, key.removesuffix("_minor"), period)) == number
    changes = result["result"]["comparison"]
    assert Decimal(changes["net_sales"]["change_rate"]) == Decimal("0.1")
    assert abs(Decimal(changes["aov"]["change_rate"]) - Decimal("-0.266666666667")) < Decimal(
        "1e-11"
    )
    assert abs(Decimal(changes["gross_margin"]["delta_pp"]) - Decimal("1.818181818182")) < Decimal(
        "1e-11"
    )
    assert changes["refund_amount"]["state"] == "new"
    assert result["result"]["contributions"]["total_minor"] == "5000"
    assert result["result"]["contributions"]["effects"] == {
        "order_effect_minor": "25000",
        "aov_effect_minor": "-20000",
    }
    assert {p["sku"]: p["sales_contribution_minor"] for p in result["products"]} == {
        "A": "-30000",
        "B": "15000",
        "C": "20000",
    }
    assert sum(Decimal(p["sales_contribution_minor"]) for p in result["products"]) == 5000
    trend = result["result"]["trend"]
    assert len(trend) == 7
    assert [p["metrics"]["net_sales"]["value"] for p in trend] == [
        "35000",
        "0",
        "0",
        "0",
        "0",
        "0",
        "20000",
    ]
    assert trend[2]["metrics"]["paid_orders"]["value"] == "1"


def test_unknown_restock_estimate_D09():
    rows = normalize_orders()["rows"]
    rows[4]["restocked_quantity"] = None
    result = compute(rows)
    assert val(result, "net_cogs") == "38000" and val(result, "gross_profit") == "17000"
    assert result["result"]["current"]["metrics"]["gross_profit"]["quality"] == "estimated"
    assert result["result"]["current"]["quality"]["estimated_restock_paid_minor"] == "10000"


def test_missing_cost_subset_and_free_gift_D10_D11():
    rows = normalize_orders()["rows"]
    rows[3]["unit_cost"] = None
    result = compute(rows)
    assert val(result, "gross_profit") is None
    matched = result["result"]["matched_cost_subset"]["metrics"]
    assert [matched[k]["value"] for k in ("net_sales", "net_cogs", "gross_profit")] == [
        "40000",
        "22000",
        "18000",
    ]
    rows = normalize_orders()["rows"]
    rows.append({**rows[3], "sku": "GIFT", "line_paid_minor": 0, "unit_cost": None})
    result = compute(rows)
    assert val(result, "cost_amount_coverage") == "1"
    assert val(result, "gross_profit") is None
    assert result["result"]["current"]["quality"]["missing_cost_rows"] == 1


def test_refund_unknown_zero_and_negative_profit_D15_D16():
    rows = normalize_orders()["rows"]
    for r in rows:
        r["line_refund_minor"] = None
    cfg = config()
    cfg["options"]["refund_mode"] = "unknown"
    result = compute(rows, cfg)
    assert val(result, "gross_sales") == "65000" and val(result, "net_sales") is None
    assert val(result, "gross_profit") is None and val(result, "aov") is None
    rows = normalize_orders()["rows"]
    for r in rows[2:]:
        r["line_refund_minor"] = r["line_paid_minor"]
        r["restocked_quantity"] = 0
    result = compute(rows)
    assert val(result, "net_sales") == "0" and val(result, "gross_profit") == "-38000"
    assert val(result, "gross_margin") is None
    assert result["result"]["comparison"]["gross_profit"]["state"] == "turned_negative"
    assert result["result"]["comparison"]["gross_profit"]["change_rate"] is None


def test_complete_empty_and_incomplete_coverage_D17_D18():
    result = compute([], q=query())
    assert val(result, "net_sales") == "0" and val(result, "gross_profit") == "0"
    assert val(result, "aov") is None
    assert result["result"]["comparison"]["net_sales"]["state"] == "both_zero"
    result = compute(normalize_orders()["rows"][2:])
    assert result["result"]["comparison"]["net_sales"]["state"] == "new"
    assert result["result"]["comparison"]["net_sales"]["change_rate"] is None
    cfg = config()
    cfg["options"]["coverage_start"] = "2026-09-28T00:00:00+08:00"
    result = compute(cfg=cfg)
    assert result["result"]["comparison"]["net_sales"]["state"] == "incomplete_coverage"
    assert result["result"]["comparison"]["net_sales"]["delta"] is None
    result = compute(
        [], cfg=cfg, q={**query(), "start": "2026-09-20", "end_exclusive": "2026-09-21"}
    )
    assert val(result, "net_sales") is None
    assert result["result"]["trend"][0]["metrics"]["net_sales"]["value"] is None


def test_half_open_dates_dst_and_week_buckets_D19_D20():
    cfg = config()
    cfg["options"].update(
        timezone="America/New_York",
        coverage_start="2026-03-01T00:00:00-05:00",
        coverage_end_exclusive="2026-03-10T00:00:00-04:00",
    )
    row = normalize_orders()["rows"][0]
    rows = [
        {**row, "paid_at": "2026-03-08T05:00:00+00:00"},
        {**row, "paid_at": "2026-03-09T03:59:59+00:00"},
        {**row, "paid_at": "2026-03-09T04:00:00+00:00"},
    ]
    result = compute(rows, cfg, {**query(), "start": "2026-03-08", "end_exclusive": "2026-03-09"})
    assert val(result, "gross_sales") == "60000"
    assert result["result"]["current"]["row_count"] == 2
    result = compute(q=query(granularity="week"))
    assert len(result["result"]["trend"]) == 1
    assert result["result"]["trend"][0]["metrics"]["net_sales"]["value"] == "55000"


def test_line_rounding_and_large_costs_stay_exact():
    rows = normalize_orders()["rows"][2:4]
    for r in rows:
        r.update(quantity=1, unit_cost="0.005", restocked_quantity=0)
    result = compute(rows)
    assert val(result, "net_cogs") == "2"  # round each 0.5 cent, not the aggregate
    rows[0].update(unit_cost="99999999999999.999999", quantity=2147483647)
    result = compute(rows)
    with __import__("decimal").localcontext() as ctx:
        ctx.prec = 70
        expected = (Decimal("99999999999999.999999") * 2147483647 * 100).quantize(
            Decimal(1), rounding="ROUND_HALF_UP"
        ) + 1
    assert Decimal(val(result, "net_cogs")) == expected


def test_sku_filter_consistency_unknown_sku_and_product_order_count():
    result = compute(q=query(skus=["B"]))
    assert val(result, "net_sales") == "15000" and val(result, "paid_orders") == "1"
    assert len(result["products"]) == 1 and result["products"][0]["sku"] == "B"
    assert (
        sum(Decimal(p["metrics"]["net_sales"]["value"]) for p in result["result"]["trend"]) == 15000
    )
    result = compute(q=query(skus=["DOES_NOT_EXIST"]))
    assert val(result, "net_sales") == "0" and not result["products"]
    result = compute()
    assert (
        sum(Decimal(p["current"]["metrics"]["paid_orders"]["value"]) for p in result["products"])
        == 4
    )
    assert val(result, "paid_orders") == "3"


@pytest.mark.parametrize(
    "current,previous,state",
    [(5, -5, "turned_positive"), (-6, -5, "negative_baseline"), (-1, 0, "turned_negative")],
)
def test_negative_baselines(current, previous, state):
    def period(v):
        return {
            "coverage_complete": True,
            "metrics": {
                "gross_profit": {
                    "value": Decimal(v),
                    "unit": "minor_currency",
                    "quality": "confirmed",
                }
            },
        }

    result = comparison(period(current), period(previous))["gross_profit"]
    assert result["state"] == state and result["change_rate"] is None


def prepare_dataset(client):
    cost_id = publish(
        client, validate(client, create_draft(client, "costs.csv", "costs"), config("costs"))
    )
    cfg = config()
    cfg["cost_version_id"] = cost_id
    return publish(client, validate(client, create_draft(client, "orders.csv", "orders"), cfg))


def test_metrics_api_cache_pagination_and_scope(api_client, db, isolated_storage):
    dataset_id = prepare_dataset(api_client)
    payload = {**query(), "dataset_id": dataset_id}
    response = api_client.post("/api/v1/metrics/query", json=payload)
    assert response.status_code == 200, response.text
    item = response.json()["data"]
    assert item["status"] == "queued"
    assert api_client.post("/api/v1/metrics/query", json=payload).json()["data"]["id"] == item["id"]
    assert run_one()
    current = api_client.get(f"/api/v1/metrics/{item['id']}").json()["data"]
    assert current["status"] == "succeeded", current
    assert current["result"]["current"]["metrics"]["net_sales"]["value"] == "55000"
    assert (
        api_client.post("/api/v1/metrics/query", json=payload).json()["data"]["status"]
        == "succeeded"
    )
    assert db.scalar(select(func.count()).select_from(MetricSnapshot)) == 1
    assert db.scalar(select(func.count()).select_from(MetricProduct)) == 3
    path = f"/api/v1/metrics/{item['id']}/products"
    assert api_client.get(path + "?limit=1&offset=1").json()["data"]["total"] == 3
    assert api_client.get(path + "?sort=gross_profit").json()["data"]["items"][0]["sku"] == "C"
    assert api_client.get(path + "?focus=refunded").json()["data"]["total"] == 1
    assert api_client.get(path + "?focus=negative_profit").json()["data"]["total"] == 0
    assert api_client.get(path + "?sort=__dict__").status_code == 422
    assert api_client.get(path + "?limit=101").status_code == 422
    assert api_client.get(f"/api/v1/datasets/{dataset_id}/skus?search=B").json()["data"] == ["B"]
    for change in (
        {"skus": ["A"]},
        {"granularity": "week"},
        {"comparison": "none"},
        {"start": "2026-09-29"},
    ):
        other = api_client.post("/api/v1/metrics/query", json={**payload, **change}).json()["data"]
        assert other["id"] != item["id"]
    foreign = Workspace(slug="metrics-foreign", name="foreign")
    db.add(foreign)
    db.flush()
    db.get(MetricSnapshot, uuid.UUID(item["id"])).workspace_id = foreign.id
    db.commit()
    assert api_client.get(f"/api/v1/metrics/{item['id']}").status_code == 404
    assert api_client.get(path).status_code == 404


def test_metrics_failed_retry_and_stale_fencing(api_client, db, isolated_storage):
    dataset_id = prepare_dataset(api_client)
    payload = {**query(), "dataset_id": dataset_id}
    first = api_client.post("/api/v1/metrics/query", json=payload).json()["data"]
    stale = claim()
    row = db.get(Job, stale.id)
    row.lease_expires_at = now() - timedelta(seconds=1)
    db.commit()
    renewed = claim()
    assert renewed.id == stale.id and renewed.lease_token > stale.lease_token
    assert not commit_result(stale, {"result": {}, "products": []})
    from app.jobs.queue import finish

    assert finish(renewed, error_code="EXECUTION_FAILED")
    assert api_client.get(f"/api/v1/metrics/{first['id']}").json()["data"]["status"] == "failed"
    retry = api_client.post("/api/v1/metrics/query", json=payload).json()["data"]
    assert retry["id"] == first["id"] and retry["job_id"] != first["job_id"]
    assert run_one()
    assert api_client.get(f"/api/v1/metrics/{first['id']}").json()["data"]["status"] == "succeeded"


def test_new_refund_snapshot_keeps_old_metric_result_D24_D25():
    old_rows = normalize_orders()["rows"]
    old_result = compute(old_rows)
    changed = copy.deepcopy(old_rows)
    changed[5]["line_refund_minor"] = 5000
    new_result = compute(changed)
    assert val(new_result, "net_sales") == "50000"
    assert val(old_result, "net_sales") == "55000"


def test_query_rejects_invalid_periods():
    for change in (
        {"end_exclusive": "2026-09-28"},
        {"end_exclusive": "2030-01-01"},
        {"comparison": "custom", "compare_start": None},
        {"skus": ["x" * 129]},
    ):
        with pytest.raises(ValueError):
            MetricQuery.model_validate({**query(), **change})


def test_product_and_day_partition_conservation():
    rng = random.Random(20261007)
    base = normalize_orders()["rows"][2]
    rows = []
    for i in range(250):
        paid = rng.randrange(1, 1000000)
        rows.append(
            {
                **base,
                "order_id": f"ORDER-{i // 2}",
                "sku": f"SKU-{i % 5}",
                "paid_at": f"2026-09-{28 + i % 3}T10:00:00+00:00",
                "line_paid_minor": paid,
                "line_refund_minor": rng.randrange(paid + 1),
                "quantity": rng.randrange(1, 8),
                "restocked_quantity": 0,
                "unit_cost": str(Decimal(rng.randrange(100000)) / 10000),
            }
        )
    output = compute(rows)
    for key in (
        "gross_sales",
        "refund_amount",
        "net_sales",
        "net_cogs",
        "gross_profit",
        "paid_units",
    ):
        total = Decimal(val(output, key))
        assert (
            sum(Decimal(p["current"]["metrics"][key]["value"]) for p in output["products"]) == total
        )
        assert sum(Decimal(p["metrics"][key]["value"]) for p in output["result"]["trend"]) == total
    assert sum(Decimal(p["sales_contribution_minor"]) for p in output["products"]) == Decimal(
        val(output, "net_sales")
    )


def test_new_published_refunds_do_not_rewrite_persisted_metrics(api_client, db, isolated_storage):
    dataset_id = prepare_dataset(api_client)
    original = api_client.post(
        "/api/v1/metrics/query", json={**query(), "dataset_id": dataset_id}
    ).json()["data"]
    assert run_one()
    cfg = config()
    cfg["cost_version_id"] = str(db.get(DatasetVersion, uuid.UUID(dataset_id)).cost_version_id)
    cfg["options"]["source_as_of"] = "2026-10-07T01:00:00+08:00"
    rows = list(csv.reader(io.StringIO((SAMPLES / "orders.csv").read_text(encoding="utf-8-sig"))))
    rows[-1][7] = "50.00"
    output = io.StringIO()
    csv.writer(output).writerows(rows)
    uploaded = api_client.post(
        "/api/v1/uploads",
        data={"kind": "orders"},
        files={"file": ("updated.csv", output.getvalue().encode(), "text/csv")},
    ).json()["data"]
    assert run_one()
    draft = api_client.post(
        "/api/v1/imports", json={"upload_id": uploaded["upload_id"], "name": "updated refunds"}
    ).json()["data"]
    revised_id = publish(api_client, validate(api_client, draft, cfg))
    revised = api_client.post(
        "/api/v1/metrics/query", json={**query(), "dataset_id": revised_id}
    ).json()["data"]
    assert revised["id"] != original["id"]
    assert run_one()
    old = api_client.get(f"/api/v1/metrics/{original['id']}").json()["data"]["result"]
    new = api_client.get(f"/api/v1/metrics/{revised['id']}").json()["data"]["result"]
    assert old["current"]["metrics"]["net_sales"]["value"] == "55000"
    assert new["current"]["metrics"]["net_sales"]["value"] == "50000"
