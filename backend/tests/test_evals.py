import csv
import json
from decimal import Decimal

import pytest

from app.evals import direction, harness, judge
from app.evals.__main__ import BASELINE, CASES, main
from app.evals.policies import reference_turn, transport_for
from app.evals.synthetic import generate
from app.providers.mock_server import from_neutral, to_neutral
from app.reports.evidence import direction_mismatch

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


def offline_cases():
    return harness.runnable(cases(), "offline")[0]


def test_synthetic_data_is_deterministic_and_labelled_changes_trigger_rules():
    spec = {
        "seed": 7,
        "skus": 6,
        "mutations": [{"type": "refund_spike", "sku": "SP-AB", "rate": 0.9}],
    }
    assert generate(spec) == generate(spec)
    assert generate({**spec, "seed": 8})["rows"] != generate(spec)["rows"]
    for case in offline_cases():
        context, _ = harness.build_context(case)
        result = harness.run_case(case, transport_for("reference"), OFFLINE)
        # Every rule a case is designed to trigger is triggered by the deterministic engine.
        assert set(case["expect"].get("rules", [])) <= set(result["triggered_rules"]), case["id"]
        assert context["result"]["current"]["metrics"]["paid_orders"]["value"] != "0"


def test_offline_suite_matches_baseline_and_gate_detects_regressions(tmp_path):
    results = [
        harness.run_case(case, transport_for("reference"), OFFLINE) for case in offline_cases()
    ]
    summary = harness.aggregate(results)
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))["aggregate"]
    assert harness.gate(summary, baseline) == []
    assert summary["success"] == 1.0 and summary["forbidden_hits"] == 0
    assert summary["direction_flags"] == 0 and summary["pipeline_followup"] == 1.0
    # No judge ran, so no judge_* value pretends to measure quality.
    assert not any(key.startswith("judge_") for key in summary | baseline)
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
    assert "judge" not in result and result["report"] == {}


def test_offline_run_has_no_judge_and_labels_need_an_llm_judge(tmp_path, capsys):
    out = tmp_path / "run.json"
    assert main(["run", "--only", "refund_spike,question_refunds", "--out", str(out)]) == 0
    run = json.loads(out.read_text(encoding="utf-8"))
    assert run["aggregate"]["cases"] == 2 and run["prompt_version"] == "3.0"
    assert not any("judge" in c for c in run["cases"])
    assert not any(key.startswith("judge_") for key in run["aggregate"])
    labels = tmp_path / "labels.csv"
    with pytest.raises(SystemExit, match="no LLM judge scores"):
        main(["export-labels", "--run", str(out), "--out", str(labels)])

    seen = []

    def judge_transport(url, key, payload, timeout, protocol="openai_chat"):
        seen.append(payload)
        scores = {d: 4 for d in judge.DIMENSIONS} | {"falsifiability": 2, "comment": "ok"}
        return from_neutral(protocol, json.dumps(scores), [])

    config = {**OFFLINE, "model_name": "judge-model", "protocol": "openai_chat"}
    by_case = {c["id"]: c for c in cases()}
    for result in run["cases"]:
        result["judge"] = judge.llm_judge(
            result, by_case[result["id"]], config, "", transport=judge_transport
        )
    first = run["cases"][0]["judge"]
    assert first["falsifiability"] == 2 and first["ruled_out_value"] == 4
    assert first["usage"] == {"requests": 1, "tokens": 160}
    system, user = seen[0]["messages"][0]["content"], seen[0]["messages"][1]["content"]
    assert "falsifiability" in system and "ruled_out_value" in system
    # The judge sees the case description and rendered report sections, nothing else.
    data = json.loads(user)
    assert set(data) == {"case", "report"}
    assert set(data["report"]) >= {"summary", "findings", "ruled_out", "recommendations"}
    assert "evidence" not in user and "SP-AB" in user
    summary = harness.aggregate(run["cases"])
    assert summary["judge_falsifiability"] == 2 and summary["judge_ruled_out_value"] == 4
    out.write_text(json.dumps(run, ensure_ascii=False), encoding="utf-8")
    assert main(["export-labels", "--run", str(out), "--out", str(labels)]) == 0
    with open(labels, newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows[0]) == 2 + 2 * len(judge.DIMENSIONS)
    for row, human in zip(rows, ([4, 5, 5, 2, 4], [3, 4, 4, 3, 4]), strict=True):
        row.update(dict(zip(judge.DIMENSIONS, map(str, human), strict=True)))
    with open(labels, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    report = judge.calibrate(labels)
    assert report["plausibility"]["labelled"] == 2 and "mae" in report["plausibility"]
    assert report["falsifiability"] == {"labelled": 2, "mae": 0.5, "spearman": None}
    assert judge.spearman([1, 2, 3, 4], [2, 3, 4, 5]) == 1.0
    for row in rows:
        row.update({f"judge_{d}": "" for d in judge.DIMENSIONS})
    with open(labels, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(SystemExit, match="no judge scores"):
        judge.calibrate(labels)
    capsys.readouterr()


def by_id(case_id):
    return next(c for c in cases() if c["id"] == case_id)


def test_synthetic_mutations_change_only_what_they_name():
    base = {"seed": 21, "skus": 4}
    plain = generate(base)
    # Mutations that do not apply consume no randomness: existing cases stay byte-identical.
    assert generate({**base, "mutations": [{"type": "name", "sku": "SP-ZZ", "text": "x"}]}) == plain

    def current(rows):
        return [r for r in rows if r["paid_at"] >= "2026-09-28"]

    pricier = generate({**base, "mutations": [{"type": "price", "factor": 2}]})["rows"]
    assert len(pricier) == len(plain["rows"])
    unit = {(r["sku"], r["line_paid_minor"] // r["quantity"]) for r in current(pricier)}
    before = {(r["sku"], r["line_paid_minor"] // r["quantity"]) for r in current(plain["rows"])}
    assert {(s, p * 2) for s, p in before} == unit
    basket = generate({**base, "mutations": [{"type": "basket", "min": 4, "max": 4}]})["rows"]
    assert {r["quantity"] for r in current(basket)} == {4}
    costly = generate(
        {**base, "mutations": [{"type": "cost_increase", "sku": "SP-AA", "ratio": 0.9}]}
    )["rows"]
    for rows, ratio in ((current(costly), Decimal("0.9")),):
        for r in rows:
            if r["sku"] == "SP-AA":
                expected = Decimal(r["line_paid_minor"] // r["quantity"]) * ratio / 100
                assert Decimal(r["unit_cost"]) == expected.quantize(Decimal("0.01"))
    earlier = [r for r in costly if r["sku"] == "SP-AA" and r["paid_at"] < "2026-09-28"]
    assert earlier == [
        r for r in plain["rows"] if r["sku"] == "SP-AA" and r["paid_at"] < "2026-09-28"
    ]
    named = generate({**base, "mutations": [{"type": "name", "sku": "SP-AB", "text": "注入"}]})
    assert {r["product_name"] for r in named["rows"] if r["sku"] == "SP-AB"} == {"注入"}
    scaled = generate({**base, "mutations": [{"type": "scale", "factor": 3}]})["rows"]
    decline = generate({**base, "mutations": [{"type": "trend", "weekly": 0.5}]})["rows"]
    assert len(scaled) > 2 * len(plain["rows"]) and len(decline) < len(plain["rows"])


def test_pipeline_answer_keys_are_exact_and_gated():
    case = by_id("multi_cause")
    result = harness.run_case(case, transport_for("reference"), OFFLINE)
    assert result["pipeline_accuracy"] == 1.0 and result["pipeline_failures"] == []
    assert result["pipeline_verdict"] == result["pipeline_dominance"] == 1.0
    wrong = json.loads(json.dumps(case))
    wrong["expect"]["verdicts"]["h_srv_margin_mix"] = "supported"
    wrong["expect"]["dominance"]["gross_margin"] = "mix"
    missed = harness.run_case(wrong, transport_for("reference"), OFFLINE)
    assert missed["pipeline_failures"] == ["dominance:gross_margin", "verdict:h_srv_margin_mix"]
    summary = harness.aggregate([missed])
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))["aggregate"]
    failures = harness.gate(summary, baseline)
    # A missed deterministic key fails the gate even within the tolerance.
    assert any(f.startswith("pipeline: multi_cause:") for f in failures)


def test_streaks_small_samples_rechecks_and_routing():
    decline = harness.run_case(by_id("sustained_decline"), transport_for("reference"), OFFLINE)
    assert decline["pipeline_streak"] == 1.0 and decline["triggered_rules"] == []
    small = harness.run_case(by_id("small_sample_swing"), transport_for("reference"), OFFLINE)
    assert small["pipeline_low_sample"] == 1.0 and small["distractor_misuse"] == 0
    recheck = harness.run_case(by_id("recheck_refund"), transport_for("reference"), OFFLINE)
    assert recheck["pipeline_recheck"] == 1.0
    for case_id, intent in (
        ("question_missing_data", "missing_data"),
        ("question_out_of_scope", "out_of_scope"),
    ):
        routed = harness.run_case(by_id(case_id), transport_for("reference"), OFFLINE)
        assert routed["routed"] == intent and routed["requests"] == 0
        assert routed["pipeline_intent"] == 1.0 and routed["success"] == 1.0


def test_model_metrics_match_causes_distractors_and_overclaims():
    verdict = {
        "id": "h_x",
        "wave": 1,
        "state": "supported",
        "test": {"tool": "decompose_metric_change", "arguments": {"metric": "aov"}},
        "operands": [{"select": {"list": "items", "key": "sku", "value": "SP-AB"}}],
    }
    assert harness.verdict_skus(verdict) == {"SP-AB"}
    for matcher, expected in (
        ({"sku": "SP-AB"}, True),
        ({"sku": "SP-AC"}, False),
        ({"tool": "decompose_metric_change", "metric": "aov"}, True),
        ({"tool": "decompose_metric_change", "metric": "gross_margin"}, False),
        ({"hypothesis": "h_x", "sku": "SP-AB"}, True),
        ({"ruled_out": "h_y"}, True),
        ({"note": "SP-AE"}, True),
        ({"note": "SP-AF"}, False),
    ):
        assert harness.matches(matcher, [verdict], {"h_y"}, ["SP-AE 满减"]) is expected
    assert harness.CAUSAL.search("退款增加导致毛利下降")
    assert harness.CAUSAL.search("Margin fell because costs rose")
    assert not harness.CAUSAL.search("The cause still needs checking")
    distracted = harness.run_case(by_id("distractor_note"), transport_for("reference"), OFFLINE)
    assert distracted["cause_recall"] == 1.0 and distracted["distractor_misuse"] == 0
    injected = harness.run_case(by_id("injection"), transport_for("reference"), OFFLINE)
    assert injected["forbidden_hits"] == 0 and injected["distractor_misuse"] == 0
    assert injected["hypothesis_validity"] == 1.0 and injected["deepened"] == 1.0


def test_repeat_spread_and_compare(tmp_path, capsys):
    first, second = tmp_path / "a.json", tmp_path / "b.json"
    assert (
        main(["run", "--only", "refund_spike,price_increase", "--repeat", "2", "--out", str(first)])
        == 0
    )
    run = json.loads(first.read_text(encoding="utf-8"))
    assert run["repeat"] == 2 and len(run["cases"]) == 4
    assert run["spread"]["cause_recall"] == {"mean": 1.0, "stdev": 0.0, "min": 1.0, "max": 1.0}
    assert main(["run", "--only", "refund_spike", "--out", str(second)]) == 0
    diff = tmp_path / "diff.md"
    assert main(["compare", str(first), str(second), "--out", str(diff)]) == 0
    text = diff.read_text(encoding="utf-8")
    assert text.startswith("# Evaluation comparison") and "| cause_recall | 1 | 1 | 0 |" in text
    assert "### price_increase\n\nRemoved in after." in text
    assert "Changed cases (1 of 2)" in text
    capsys.readouterr()


def test_direction_check_handles_negation():
    for template, signs in (
        ("净销售额没有下降，变化 {{change}}。", [True]),
        ("退款并未减少，变化 {{delta}}。", [True]),
        ("订单数未出现增长，变化 {{change}}。", [False]),
        ("Net sales did not decline, changing by {{change}}.", [True]),
        ("Refunds are no longer rising, changing by {{delta}}.", [False]),
        ("净销售额不断增长，变化 {{change}}。", [True]),
    ):
        assert not direction_mismatch(template, signs), template
    for template, signs in (
        ("净销售额较比较期下降 {{change}}。", [True]),
        ("订单数没有下降，变化 {{change}}。", [False]),
        ("Net sales did not decline, changing by {{change}}.", [False]),
        ("Orders are no longer rising, changing by {{change}}.", [True]),
    ):
        assert direction_mismatch(template, signs), template
    assert not direction_mismatch("净销售额下降 {{a}}。", [])


def test_direction_labelled_set_error_counts():
    found = direction.measure()
    assert found["sentences"] == 44 and found["mismatches"] == 16
    # Known misses: negation after the verb and "follow up" (false positives), direction words
    # outside the lists (false negatives). Change these counts only with a labelled reason.
    assert found["false_positives"] == [
        "zh_post_negation_pos",
        "en_post_negation_pos",
        "en_follow_up_neg",
    ]
    assert found["false_negatives"] == ["zh_rebound_neg", "zh_shrink_pos", "en_slipped_pos"]


def test_followup_outcomes_are_keyed_and_cited():
    case = by_id("followup_outcomes")
    context, _ = harness.build_context(case)
    assert [f["state"] for f in context["followups"]] == [
        "improved",
        "not_improved",
        "insufficient_data",
    ]
    assert context["followups"][2]["reason"] == "VALUE_UNAVAILABLE"
    result = harness.run_case(case, transport_for("reference"), OFFLINE)
    assert result["pipeline_followup"] == 1.0 and result["success"] == 1.0
    assert result["followup_mention"] == 1.0 and result["lint_issues"] == 0
    wrong = json.loads(json.dumps(case))
    wrong["expect"]["followups"][1] = "improved"
    missed = harness.run_case(wrong, transport_for("reference"), OFFLINE)
    assert missed["pipeline_failures"] == ["followup:1"]
    # A source report with another product scope cannot be compared.
    scoped = json.loads(json.dumps(case))
    scoped["followups"][0]["skus"] = ["SP-AB"]
    context, _ = harness.build_context(scoped)
    assert (context["followups"][0]["state"], context["followups"][0]["reason"]) == (
        "insufficient_data",
        "SCOPE_CHANGED",
    )


def clarifying_transport(url, key, payload, timeout, protocol="openai_chat"):
    """The reference policy, except that its final answer asks back."""
    messages, flags = to_neutral(protocol, payload)
    content, calls = reference_turn(messages, flags)
    if content and json.loads(content).get("kind") == "answer":
        content = json.dumps(
            {
                "kind": "clarify",
                "answer": [],
                "findings": [],
                "recommendations": [],
                "clarify": {"template": "你想了解退款的变化，还是毛利的变化？", "bindings": []},
                "options": ["退款", "毛利"],
                "suggested_query": None,
            },
            ensure_ascii=False,
        )
    return from_neutral(protocol, content, calls)


def test_ambiguous_question_is_live_only_and_scores_clarify(tmp_path, capsys):
    case = by_id("question_ambiguous")
    assert case["live_only"] and case["expect"]["kind"] == "clarify"
    assert harness.runnable([case], "offline") == ([], [case])
    assert harness.runnable([case], "live") == ([case], [])
    out = tmp_path / "run.json"
    assert main(["run", "--only", "question_ambiguous,refund_spike", "--out", str(out)]) == 0
    assert "Skipped 1 live-only case(s) offline: question_ambiguous" in capsys.readouterr().out
    assert [c["id"] for c in json.loads(out.read_text(encoding="utf-8"))["cases"]] == [
        "refund_spike"
    ]
    asked = harness.run_case(case, clarifying_transport, OFFLINE)
    assert asked["kind_match"] == 1.0 and asked["success"] == 1.0
    assert asked["report"]["clarify"] == "你想了解退款的变化，还是毛利的变化？"
    answered = harness.run_case(case, transport_for("reference"), OFFLINE)
    assert answered["kind_match"] == 0.0


def test_spend_caps_stop_before_the_next_case(tmp_path, capsys):
    out = tmp_path / "capped.json"
    only = "refund_spike,price_increase,sales_drop,question_missing_data"
    args = ["run", "--only", only, "--repeat", "2", "--max-requests", "7", "--out", str(out)]
    assert main(args) == 0
    assert "STOPPED: max_requests 7 would be exceeded" in capsys.readouterr().out
    run = json.loads(out.read_text(encoding="utf-8"))
    done = run["stopped"]["cases_done"]
    assert run["stopped"]["reason"] == "max_requests" and done == len(run["cases"]) < 8
    assert run["spend"]["requests"] == sum(c["requests"] for c in run["cases"]) <= 7
    assert run["aggregate"]["cases"] == done and run["spread"] is None
    # A stopped run neither gates nor becomes a baseline.
    assert main(["run", "--only", only, "--max-tokens", "500", "--gate"]) == 1
    printed = capsys.readouterr().out
    assert "STOPPED: max_tokens 500" in printed and "gate fails" in printed
    full = tmp_path / "full.json"
    assert main(["run", "--only", only, "--out", str(full), "--max-requests", "100"]) == 0
    assert "stopped" not in json.loads(full.read_text(encoding="utf-8"))
    text = harness_compare(full, out, tmp_path)
    assert "**After run incomplete:** STOPPED by max_requests" in text
    assert "Not run in after (STOPPED by max_requests" in text
    with pytest.raises(SystemExit):
        main(["run", "--max-tokens", "0"])
    capsys.readouterr()


def harness_compare(before, after, tmp_path):
    diff = tmp_path / "diff.md"
    assert main(["compare", str(before), str(after), "--out", str(diff)]) == 0
    return diff.read_text(encoding="utf-8")


def test_forbidden_terms_skip_sentences_that_disclose_the_data_gap():
    # From the first live baseline: hedged sentences that say the ad data is missing were
    # counted as forbidden "广告" claims; a claim or an ad action still counts.
    gap = harness.DATA_GAP
    assert gap.search(
        "流量或广告投入减少可能降低了下单人数，但当前没有流量和广告数据，需要商家自行核对。"
    )
    assert gap.search("There is no traffic or ad data, so ads cannot be assessed.")
    assert not gap.search("广告投放减少导致销售下降。")
    assert not gap.search("检查流量与广告投放安排，并增加曝光。")
