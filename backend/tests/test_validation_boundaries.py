"""Input boundary cases: reject ambiguous money/coverage and malformed source rows."""

import pytest
from pydantic import ValidationError

from app.ingestion.normalize import normalize, number, timestamp
from app.ingestion.parser import parse
from app.metrics.schema import MetricValue
from tests.test_ingestion import SAMPLES, config, errors, normalize_orders, parsed_orders
from tests.test_metrics import query


@pytest.mark.parametrize(
    "value", ["", "1e3", "NaN", "1,000", "9007199254740992", "0.12345678901234567890123456789"]
)
def test_ambiguous_or_unsafe_numbers(value):
    with pytest.raises(ValueError):
        number(value)


def test_locale_decimal_and_invalid_timestamp():
    assert str(number("12,50", ",")) == "12.50"
    with pytest.raises(ValueError):
        timestamp("not-a-date", "Asia/Shanghai")


@pytest.mark.parametrize(
    "field,value",
    [
        ("order_id", ""),
        ("order_id", "x" * 129),
        ("order_id", "合计"),
        ("quantity", "0"),
        ("quantity", "1.5"),
        ("quantity", "2147483648"),
        ("line_paid", "-1"),
        ("line_paid", "0.001"),
        ("paid_at", "2026-10-05T00:00:00+08:00"),
        ("restocked_quantity", "-1"),
        ("restocked_quantity", "4"),
    ],
)
def test_invalid_order_fields_never_publish(field, value):
    data = parsed_orders()
    data["rows"][0]["values"][field] = value
    result = normalize_orders(data)
    assert any(i["code"] == "INVALID_ROW" and i["row_number"] == 2 for i in errors(result))
    assert all(r["source_row_number"] != 2 for r in result["rows"])


@pytest.mark.parametrize(
    "case,code",
    [
        ("mapping", "MAPPING_REQUIRED"),
        ("column", "COLUMN_NOT_FOUND"),
        ("semantics", "SEMANTICS_REQUIRED"),
        ("exclude", "INVALID_EXCLUSION"),
        ("coverage", "COVERAGE_INVALID"),
        ("confirm", "COVERAGE_REQUIRED"),
    ],
)
def test_global_validation_blocks_all_rows(case, code):
    cfg, resolutions = config(), {}
    if case == "mapping":
        del cfg["columns"]["quantity"]
    elif case == "column":
        cfg["columns"]["quantity"] = "nonexistent"
    elif case == "semantics":
        cfg["options"]["semantics_confirmed"] = False
    elif case == "exclude":
        resolutions["excluded_rows"] = [999]
    elif case == "coverage":
        cfg["options"]["coverage_start"] = "2026-10-10"
    else:
        cfg["options"]["coverage_confirmed"] = False
    result = normalize_orders(cfg=cfg, resolutions=resolutions)
    assert not result["rows"] and code in result["summary"]["issue_counts"]


def test_workbook_warning_and_numeric_identifier_precision():
    data = parsed_orders()
    data["warnings"] = ["HIDDEN_ROWS"]
    data["rows"][0]["numeric"] = ["order_id"]
    data["rows"][0]["values"]["order_id"] = "123"
    result = normalize_orders(data)
    assert {"NUMERIC_IDENTIFIER", "HIDDEN_ROWS"} <= set(result["summary"]["warning_codes"])
    data["rows"][0]["values"]["order_id"] = "1234567890123456"
    assert errors(normalize_orders(data))
    data["rows"][0]["numeric"] = []
    data["rows"][0]["formulas"] = ["product_name"]
    assert errors(normalize_orders(data))


@pytest.mark.parametrize("value", ["-1", "0.1234567", "100000000000000"])
def test_invalid_unit_cost_bounds(value):
    data = parse(SAMPLES / "costs.csv", {})
    data["rows"][0]["values"]["unit_cost"] = value
    result = normalize(data, "costs", config("costs"), {}, "hash", [])
    assert errors(result) and all(r["source_row_number"] != 2 for r in result["rows"])


def test_zero_cost_warns_and_reversed_cost_interval_blocks():
    data = parse(SAMPLES / "costs.csv", {})
    data["rows"][0]["values"]["unit_cost"] = "0"
    result = normalize(data, "costs", config("costs"), {}, "hash", [])
    assert "ZERO_COST" in result["summary"]["warning_codes"]
    data["rows"][0]["values"].update(effective_from="2026-10-01", effective_to="2026-09-01")
    assert errors(normalize(data, "costs", config("costs"), {}, "hash", []))


def test_missing_sku_and_excluding_all_rows():
    data = parsed_orders()
    data["rows"][0]["values"]["sku"] = ""
    assert "SKU_MISSING" in normalize_orders(data)["summary"]["warning_codes"]
    result = normalize_orders(
        data, resolutions={"excluded_rows": [r["row_number"] for r in data["rows"]]}
    )
    assert "EMPTY_RESULT" in result["summary"]["issue_counts"]


def test_unmapped_payment_state_and_derived_negative_money():
    cfg, data = config(), parsed_orders()
    cfg["options"].update(payment_state_mode="mapped", status_mapping={})
    cfg["columns"]["payment_state"] = "sku"
    assert errors(normalize_orders(data, cfg))
    cfg = config()
    cfg["options"]["amount_scope"] = "derived"
    cfg["columns"].update(unit_price="line_refund", discount_minor="line_paid")
    assert errors(normalize_orders(data, cfg))


def test_order_conflicts_refund_and_amount_overflow():
    data = parsed_orders()
    # Golden order O1000 has two rows: contradictory timestamps cannot merge into one order.
    data["rows"][3]["values"]["paid_at"] = "2026-09-29T10:00:00+08:00"
    assert "ORDER_CONFLICT" in normalize_orders(data)["summary"]["issue_counts"]
    data = parsed_orders()
    for row in data["rows"]:
        row["values"]["line_paid"] = "80000000000000"
    assert "TOTAL_OVERFLOW" in normalize_orders(data)["summary"]["issue_counts"]


@pytest.mark.parametrize(
    "value,quality,reason",
    [
        (None, "confirmed", None),
        (None, "unavailable", None),
        ("1", "unavailable", "missing"),
        ("1", "confirmed", "missing"),
    ],
)
def test_metric_availability_cannot_contradict_value(value, quality, reason):
    with pytest.raises(ValidationError):
        MetricValue(value=value, unit="count", quality=quality, unavailable_reason=reason)


def test_reversed_custom_comparison_is_rejected():
    with pytest.raises(ValidationError):
        query(comparison="custom", compare_start="2026-10-05", compare_end_exclusive="2026-09-28")
