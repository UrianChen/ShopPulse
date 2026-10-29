"""SKU drill-down payload computed with the metrics engine over frozen order lines."""

from app.metrics.engine import calculate
from app.metrics.schema import MetricQuery
from app.reports.tools import KEY_METRICS


def scoped_query(query, sku):
    return MetricQuery.model_validate({**query, "skus": [sku]})


def drill_payload(sku, rows, snapshot, query):
    result = calculate(rows, snapshot, scoped_query(query, sku).model_dump(mode="json"))["result"]

    def period(data):
        if not data:
            return None
        return {"metrics": data["metrics"], "coverage_complete": data["coverage_complete"]}

    return {
        "sku": sku,
        "product_name": rows[0]["product_name"],
        "current": period(result["current"]),
        "previous": period(result["previous"]),
        "comparison": result["comparison"],
        "trend": [
            {
                "start": p["start"],
                "end_exclusive": p["end_exclusive"],
                "metrics": {k: p["metrics"][k] for k in KEY_METRICS},
            }
            for p in result["trend"]
        ],
    }
