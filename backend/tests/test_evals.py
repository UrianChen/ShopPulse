import csv
import json

from app.evals import harness, judge
from app.evals.__main__ import BASELINE, CASES, main
from app.evals.policies import transport_for
from app.evals.synthetic import generate

OFFLINE = {
    "base_url": "https://eval.invalid/v1",
    "model_name": "reference",
    "timeout_seconds": 30,
    "token_limit_parameter": "none",
    "product_name_mode": "sku_only",
    "capabilities": {"usable": True, "strategy": "native_tools", "native_json": True},
}


def cases():
    return json.loads(CASES.read_text(encoding="utf-8"))["cases"]


def test_synthetic_data_is_deterministic_and_labelled_changes_trigger_rules():
    spec = {
        "seed": 7,
        "skus": 6,
        "mutations": [{"type": "refund_spike", "sku": "SP-AB", "rate": 0.9}],
    }
    assert generate(spec) == generate(spec)
    assert generate({**spec, "seed": 8})["rows"] != generate(spec)["rows"]
    for case in cases():
        context, _ = harness.build_context(case)
        result = harness.run_case(case, transport_for("reference"), OFFLINE)
        # Every rule a case is designed to trigger is triggered by the deterministic engine.
        assert set(case["expect"].get("rules", [])) <= set(result["triggered_rules"]), case["id"]
        assert context["result"]["current"]["metrics"]["paid_orders"]["value"] != "0"


def test_offline_suite_matches_baseline_and_gate_detects_regressions(tmp_path):
    results = [harness.run_case(case, transport_for("reference"), OFFLINE) for case in cases()]
    summary = harness.aggregate(results)
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))["aggregate"]
    assert harness.gate(summary, baseline) == []
    assert summary["success"] == 1.0 and summary["forbidden_hits"] == 0
    worse = {**summary, "entity_coverage": summary["entity_coverage"] - 0.2, "forbidden_hits": 1}
    failures = harness.gate(worse, baseline)
    assert any(f.startswith("entity_coverage") for f in failures)
    assert any(f.startswith("forbidden_hits") for f in failures)


def test_scripted_failure_policy_is_scored_as_failure():
    case = next(c for c in cases() if c["id"] == "refund_spike")
    result = harness.run_case(
        case,
        transport_for("bad-number"),
        {
            **OFFLINE,
            "model_name": "bad-number",
            "capabilities": {"usable": True, "strategy": "narrative"},
        },
    )
    assert result["success"] == 0.0 and result["error_code"] == "EVIDENCE_VALIDATION_FAILED"
    assert result["repairs"] == 2 and result["entity_coverage"] == 0.0
    assert judge.heuristic_judge(result)["plausibility"] == 1


def test_cli_run_gate_export_and_calibration(tmp_path, capsys):
    out = tmp_path / "run.json"
    assert main(["run", "--only", "refund_spike,question_refunds", "--out", str(out)]) == 0
    run = json.loads(out.read_text(encoding="utf-8"))
    assert run["aggregate"]["cases"] == 2 and run["prompt_version"] == "2.0"
    assert all(c["judge"]["judge"] == "heuristic" for c in run["cases"])
    labels = tmp_path / "labels.csv"
    assert main(["export-labels", "--run", str(out), "--out", str(labels)]) == 0
    with open(labels, newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    for row, human in zip(rows, ([4, 5, 5], [3, 4, 4]), strict=True):
        row.update(dict(zip(judge.DIMENSIONS, map(str, human), strict=True)))
    with open(labels, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    report = judge.calibrate(labels)
    assert report["plausibility"]["labelled"] == 2 and "mae" in report["plausibility"]
    assert judge.spearman([1, 2, 3, 4], [2, 3, 4, 5]) == 1.0
    capsys.readouterr()
