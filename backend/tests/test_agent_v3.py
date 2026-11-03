"""Agent v3: derive, decompositions, history, small samples, hypotheses, patches and review."""

import json
import uuid
from decimal import Decimal
from pathlib import Path

import pytest

from app.evals.harness import build_context
from app.evals.policies import transport_for
from app.evals.synthetic import generate
from app.metrics.engine import calculate, history
from app.providers.egress import ProviderError
from app.providers.mock_server import from_neutral, phase_message, respond, to_neutral
from app.providers.protocols import build, parse
from app.reports import patches, service
from app.reports.derive import DeriveError, compute, flagged, operand
from app.reports.evidence import lint, validate_analysis
from app.reports.grammar import EvidenceError
from app.reports.hypothesis import seed
from app.reports.schema import PROMPT_VERSION, QUESTION_BUDGETS
from app.reports.tools import ToolError, ToolRegistry, history_payload, metric_facts
from app.reports.workflow import ReportWorkflow
from tests.test_metrics import prepare_dataset
from tests.test_reports import create_report, finish_report, model_config
from tests.test_reports import provider as mock_provider_fixture

provider = mock_provider_fixture
CASES = {
    c["id"]: c for c in json.loads(Path("evals/cases.json").read_text(encoding="utf-8"))["cases"]
}


def registry_for(case_id, **options):
    context, drill = build_context(CASES[case_id])
    registry = ToolRegistry(context, str(uuid.uuid4()), str(uuid.uuid4()), drill=drill, **options)
    return registry, registry.core(), context, drill


def request_for(registry, context, model="agent", strategy="native_tools", kind="report"):
    result = context["result"]
    return {
        "config": {
            "base_url": "https://eval.invalid/v1",
            "model_name": model,
            "protocol": "openai_chat",
            "timeout_seconds": 5,
            "token_limit_parameter": "none",
            "product_name_mode": "sku_only",
            "capabilities": {"usable": True, "strategy": strategy, "native_json": True},
        },
        "key": "",
        "context": context,
        "evidence": list(registry.evidence),
        "report_id": registry.report_id,
        "run_id": registry.run_id,
        "kind": kind,
        "intent": "refund_review" if kind == "question" else "business_review",
        "language": "zh",
        "dataset_id": result["dataset_id"],
        "currency": result["currency"],
        "currency_exponent": result["currency_exponent"],
        "scope": result["query"],
        "question": "退款为什么高？" if kind == "question" else None,
        "prompt_version": PROMPT_VERSION,
    }


def analysis_with(sentence, evidence):
    fact = metric_facts(evidence)[0]
    return {
        "summary": [sentence],
        "findings": [
            {
                "id": "f_sales",
                "topic": "sales",
                "title": "销售",
                "observation": fact,
                "supporting": [],
                "hypotheses": [],
            }
        ],
        "recommendations": [
            {
                "action": {"template": "复核主要商品", "bindings": []},
                "rationale_finding_ids": ["f_sales"],
                "priority": "medium",
                "effort": "small",
                "verification_metric": "net_sales",
                "suggested_review_window": "next_week",
            }
        ],
    }


def check(registry, context, raw):
    result = context["result"]
    return validate_analysis(
        raw,
        registry.known(),
        registry.report_id,
        result["dataset_id"],
        result["currency"],
        result["currency_exponent"],
        result["query"],
    )


def test_decompositions_add_up_exactly():
    for case_id in ("refund_spike", "sales_drop", "negative_margin", "concentration"):
        data = generate(CASES[case_id]["data"])
        result = calculate(data["rows"], data["snapshot"], data["query"])["result"]
        for metric in ("gross_margin", "refund_amount_rate"):
            d = result["decompositions"][metric]
            assert d["available"], (case_id, metric)
            parts = sum(Decimal(d[k]) for k in ("mix_effect_pp", "rate_effect_pp", "other_pp"))
            assert abs(parts - Decimal(d["delta_pp"])) < Decimal("1e-9")
            expected = Decimal(result["comparison"][metric]["delta_pp"])
            assert abs(Decimal(d["delta_pp"]) - expected) < Decimal("1e-9")
        aov = result["decompositions"]["aov"]
        effects = Decimal(aov["price_effect_minor"]) + Decimal(aov["basket_effect_minor"])
        assert abs(effects - Decimal(aov["delta_minor"])) < Decimal("1e-6")
        assert abs(Decimal(aov["delta_minor"]) - Decimal(result["comparison"]["aov"]["delta"])) < 1
    # The refund spike is a rate change on one SKU, not a change of product mix.
    data = generate(CASES["refund_spike"]["data"])
    spike = calculate(data["rows"], data["snapshot"], data["query"])["result"]
    refund = spike["decompositions"]["refund_amount_rate"]
    assert refund["items"][0]["sku"] == "SP-AB"
    assert abs(Decimal(refund["rate_effect_pp"])) > abs(Decimal(refund["mix_effect_pp"]))


def test_history_windows_streaks_and_incomplete_coverage():
    data = generate(CASES["sales_drop"]["data"])
    result = calculate(data["rows"], data["snapshot"], data["query"])["result"]
    windows, days = service.history_windows(result["query"])
    assert days == 7 and len(windows) == 8 and windows[-1][1] == result["query"]["start"]
    raw = history(data["rows"], data["snapshot"], windows)
    payload = history_payload(raw, result, days)
    assert payload["windows"][0]["start"] == windows[-1][0]  # newest first
    oldest = payload["windows"][-1]
    assert not oldest["coverage_complete"]  # starts before the synthetic coverage
    assert oldest["metrics"]["net_sales"]["value"] is None
    assert payload["windows"][0]["coverage_complete"]
    synthetic = {
        "windows": [
            {
                "start": f"2026-09-0{i + 1}",
                "end_exclusive": f"2026-09-0{i + 2}",
                "coverage_complete": True,
                "metrics": {
                    k: {"value": v, "unit": "minor_currency", "quality": "confirmed"}
                    for k in ("net_sales", "paid_orders", "aov", "gross_margin")
                }
                | {"refund_amount_rate": {"value": None, "unit": "ratio", "quality": "x"}},
            }
            for i, v in enumerate(["300", "200", "100"])
        ]
    }
    current = {
        "coverage_complete": True,
        "metrics": {k: {"value": "50"} for k in ("net_sales", "paid_orders", "aov", "gross_margin")}
        | {"refund_amount_rate": {"value": "0.1"}},
    }
    streaks = history_payload(synthetic, {"current": current}, 1)["streaks"]
    assert streaks["net_sales"] == {"direction": "down", "periods": 3}
    assert "refund_amount_rate" not in streaks


def test_derive_unit_rules():
    registry, core, _, _ = registry_for("refund_spike")
    metrics = core["calculate_metrics"]
    ranked = core["rank_products"]
    current = operand(metrics, "current.metrics.net_sales")
    previous = operand(metrics, "previous.metrics.net_sales")
    assert compute("multiple", current, previous)["unit"] == "multiple"
    share = compute("share", operand(ranked, "items.0.current.metrics.net_sales"), current)
    assert 0 < Decimal(share["value"]) <= 1 and share["unit"] == "ratio"
    margin = compute(
        "diff",
        operand(metrics, "current.metrics.refund_amount_rate"),
        operand(metrics, "previous.metrics.refund_amount_rate"),
    )
    assert margin["unit"] == "pp" and margin["signed"]
    for op, a, b, code in [
        ("ratio", "current.metrics.net_sales", "current.metrics.paid_orders", "UNIT_MISMATCH"),
        ("share", "current.metrics.refund_amount", "current.metrics.net_sales", "METRIC_MISMATCH"),
        ("diff", "current.metrics.net_sales", "current.metrics.refund_amount", "METRIC_MISMATCH"),
    ]:
        with pytest.raises(DeriveError, match=code):
            compute(op, operand(metrics, a), operand(metrics, b))
    with pytest.raises(DeriveError, match="NOT_A_TOTAL"):
        compute(
            "share",
            operand(ranked, "items.1.current.metrics.net_sales"),
            operand(ranked, "items.0.current.metrics.net_sales") | {"evidence_id": "other"},
        )
    with pytest.raises(DeriveError, match="PATH_NOT_ALLOWED"):
        operand(core["detect_anomalies"], "thresholds.min_orders")
    tool = registry.execute(
        "derive",
        {
            "op": "multiple",
            "a": {"evidence_id": metrics["evidence_id"], "path": "current.metrics.net_sales"},
            "b": {"evidence_id": metrics["evidence_id"], "path": "previous.metrics.net_sales"},
        },
    )
    assert tool["payload"]["result"]["unit"] == "multiple"
    with pytest.raises(ToolError, match="DERIVE_UNIT_MISMATCH"):
        registry.execute(
            "derive",
            {
                "op": "ratio",
                "a": {"evidence_id": metrics["evidence_id"], "path": "current.metrics.net_sales"},
                "b": {"evidence_id": metrics["evidence_id"], "path": "current.metrics.paid_orders"},
            },
        )


def test_computed_binding_renders_multiple_and_records_derived_evidence():
    registry, core, context, _ = registry_for("concentration")
    ev = core["calculate_metrics"]["evidence_id"]
    binding = {
        "name": "times",
        "evidence_id": ev,
        "path": "current.metrics.net_sales",
        "format": "multiple",
        "derive": {
            "op": "multiple",
            "b": {"evidence_id": ev, "path": "previous.metrics.net_sales"},
        },
    }
    raw = analysis_with(
        {"template": "本期是比较期的 {{times}}。", "bindings": [binding]}, registry.evidence
    )
    first = check(registry, context, raw)
    text = first["summary"][0]["text"]
    assert text.startswith("本期是比较期的 ") and text.endswith(" 倍。")
    derived = first["derived_evidence"]
    assert len(derived) == 1 and derived[0]["tool"] == "derive"
    assert derived[0]["evidence_id"] in first["summary"][0]["evidence_refs"]
    assert (
        check(registry, context, raw)["derived_evidence"][0]["evidence_id"]
        == derived[0]["evidence_id"]
    )  # deterministic id: repairs and reruns collapse
    wrong = json.loads(json.dumps(raw))
    wrong["summary"][0]["bindings"][0]["format"] = "percent"
    with pytest.raises(EvidenceError) as error:
        check(registry, context, wrong)
    assert error.value.issues[0]["code"] == "WRONG_FORMAT"
    wrong["summary"][0]["bindings"][0]["derive"]["b"]["path"] = "current.metrics.paid_orders"
    with pytest.raises(EvidenceError) as error:
        check(registry, context, wrong)
    assert error.value.issues[0]["code"] == "DERIVE_UNIT_MISMATCH"
    # Number words stay forbidden in free text even though "倍" may now be rendered.
    raw["summary"][0]["template"] = "本期翻倍为 {{times}}。"
    with pytest.raises(EvidenceError, match="UNBOUND_NUMBER_OR_CLAIM"):
        check(registry, context, raw)


def test_small_sample_change_needs_store_level_support_and_paths_get_hints():
    registry, core, context, _ = registry_for("refund_spike")
    ranked = registry.execute(
        "rank_products", {"metric": "net_sales", "direction": "asc", "top_k": 50}
    )
    items = ranked["payload"]["items"]
    index = next(i for i, p in enumerate(items) if p["sample"] == "low" and p["comparison"])
    sku = {"name": "sku", "evidence_id": ranked["evidence_id"], "path": f"items.{index}.sku"}
    change = {
        "name": "change",
        "evidence_id": ranked["evidence_id"],
        "path": f"items.{index}.comparison.net_sales.change_rate",
        "format": "percent",
    }
    alone = {
        "template": "{{sku}} 的变化为 {{change}}。",
        "bindings": [sku | {"format": "entity"}, change],
    }
    with pytest.raises(EvidenceError) as error:
        check(registry, context, analysis_with(alone, registry.evidence))
    assert error.value.issues[0]["code"] == "LOW_SAMPLE_ONLY"
    store = {
        "name": "total",
        "evidence_id": core["compare_periods"]["evidence_id"],
        "path": "comparison.net_sales.change_rate",
        "format": "percent",
    }
    supported = {
        "template": "全店变化 {{total}}，{{sku}} 的变化为 {{change}}。",
        "bindings": [store, sku | {"format": "entity"}, change],
    }
    check(registry, context, analysis_with(supported, registry.evidence))
    typo = {
        "template": "首位商品为 {{x}}。",
        "bindings": [
            {
                "name": "x",
                "evidence_id": ranked["evidence_id"],
                "path": "items.0.metrics.net_sales",
                "format": "money",
            }
        ],
    }
    with pytest.raises(EvidenceError) as error:
        check(registry, context, analysis_with(typo, registry.evidence))
    assert (
        "closest bindable path: items.0.current.metrics.net_sales" in error.value.issues[0]["hint"]
    )


def spec(identifier, tool, arguments, expect, statement="退款主要集中在单个商品上。"):
    return {
        "id": identifier,
        "statement": {"template": statement, "bindings": []},
        "test": {"tool": tool, "arguments": arguments},
        "expect": expect,
    }


def test_hypothesis_verdicts_selectors_and_guards():
    registry, core, _, _ = registry_for("refund_spike", test_limit=7)
    refunds = {"by": "sku", "top_k": 5}
    select = {"list": "items", "key": "sku", "value": "SP-AB"}

    def share(threshold):
        return {
            "op": "share_ge",
            "a": {"source": "test", "path": "metrics.refund_amount", "select": select},
            "b": {"source": "test", "path": "total.metrics.refund_amount", "select": None},
            "threshold": threshold,
        }

    held = registry.execute(
        "test_hypothesis", spec("h_ab", "refund_breakdown", refunds, share("0.5"))
    )
    assert held["payload"]["state"] == "supported"
    assert held["payload"]["derived"]["unit"] == "ratio"
    assert held["payload"]["spec"]["expect"]["a"]["select"] == select
    refuted = registry.execute(
        "test_hypothesis", spec("h_ab_all", "refund_breakdown", refunds, share("0.99"))
    )
    assert refuted["payload"]["state"] == "refuted"
    rank = registry.execute(
        "test_hypothesis",
        spec(
            "h_ab_rank",
            "refund_breakdown",
            refunds,
            {"op": "rank_le", "a": {"source": "test", "path": "", "select": select}, "k": 1},
        ),
    )
    assert rank["payload"]["state"] == "supported"
    for expect, code in [
        (
            {"op": "gt", "a": {"source": "test", "path": "total.metrics.refund_amount"}},
            "INVALID_PREDICATE_TRIVIAL_PREDICATE",
        ),
        (
            {
                "op": "gt",
                "a": {
                    "source": core["compare_periods"]["evidence_id"],
                    "path": "comparison.refund_amount.delta",
                },
            },
            "PREDICATE_MUST_USE_TEST",
        ),
    ]:
        with pytest.raises(ToolError, match=code):
            registry.execute("test_hypothesis", spec("h_bad", "refund_breakdown", refunds, expect))
    with pytest.raises(ToolError, match="TEST_TOOL_NOT_ALLOWED"):
        registry.execute(
            "test_hypothesis", spec("h_x", "explain_metric", {"metric": "aov"}, share("0.5"))
        )
    with pytest.raises(ToolError, match="INVALID_STATEMENT"):
        registry.execute(
            "test_hypothesis",
            spec("h_num", "refund_breakdown", refunds, share("0.5"), "退款增加了一倍"),
        )
    with pytest.raises(ToolError, match="TEST_BUDGET"):
        registry.execute(
            "test_hypothesis", spec("h_more", "refund_breakdown", refunds, share("0.6"))
        )


def test_server_seeds_hypotheses_and_rechecks_them_next_period():
    registry, core, _, _ = registry_for("refund_spike")
    verdicts, _ = seed(registry, core, "zh")
    states = {v["payload"]["id"]: v["payload"]["state"] for v in verdicts}
    assert states["h_srv_refund_concentrated"] == "supported"
    assert states["h_srv_refund_rate"] == "supported"
    items = service.hypothesis_items(registry.evidence)
    prior = [
        {
            "id": h["id"],
            "statement": h["statement"],
            "previous_state": h["state"],
            "source_report_id": registry.report_id,
            "spec": h["spec"],
        }
        for h in items
    ]
    later, later_core, _, _ = registry_for("stable_week")
    _, rechecked = seed(later, later_core, "zh", prior)
    result = {i["id"]: i for i in rechecked["payload"]["items"]}
    assert {i["previous_state"] for i in result.values()} == {"supported"}
    # Without the injected spike, refunds no longer move with the SKU's own refund rate.
    assert result["h_srv_refund_rate"]["state"] == "refuted"
    assert result["h_srv_refund_concentrated"]["statement"] == items[0]["statement"]


def test_hypothesis_workflow_plans_tests_refines_and_cites():
    registry, core, context, drill = registry_for("refund_spike")
    seed(registry, core, "zh")
    request = request_for(registry, context)
    output = ReportWorkflow(request, transport_for("agent"), drill=drill).run()
    assert output["error_code"] is None and output["mode"] == "hypotheses"
    tests = [s for s in output["steps"] if s["phase"] == "test"]
    assert [s["state"] for s in tests] == ["supported", "supported", "supported"]
    waves = [s["wave"] for s in output["steps"] if s["phase"] == "hypotheses"]
    assert waves == [1, 2]
    assert output["usage"]["requests"] == 3 and output["usage"]["tools"] == 0
    cited = output["analysis"]["findings"][0]["supported_hypotheses"]
    assert cited and all(h["text"] for h in cited)
    # Parent re-validation with its own evidence (core, seeded and the run's extra evidence).
    full = registry.known() + output["extra_evidence"]
    result = context["result"]
    validate_analysis(
        output["raw_analysis"],
        full,
        registry.report_id,
        result["dataset_id"],
        "CNY",
        2,
        result["query"],
    )
    raw = json.loads(json.dumps(output["raw_analysis"]))
    raw["findings"][0]["hypothesis_ids"] = ["h_unknown"]
    with pytest.raises(EvidenceError, match="UNKNOWN_HYPOTHESIS"):
        validate_analysis(raw, full, registry.report_id, result["dataset_id"], "CNY", 2)


def test_patch_repair_and_plan_fallback():
    registry, core, context, drill = registry_for("refund_spike")
    seed(registry, core, "zh")
    sent = []

    def recording(model):
        def transport(url, key, payload, timeout, protocol="openai_chat"):
            sent.append(payload)
            status, body = respond(protocol, {**payload, "model": model})
            return body

        return transport

    output = ReportWorkflow(
        request_for(registry, context, "repair-once"), recording("repair-once")
    ).run()
    assert output["error_code"] is None and output["repairs"] == 1
    repair = next(s for s in output["steps"] if s["phase"] == "repair")
    assert repair["mode"] == "patch"
    patch_request = sent[-1]["messages"][-1]["content"]
    assert "Return only patches" in patch_request and "- summary[0]: a Sentence" in patch_request
    assert "999999" not in patch_request
    sent.clear()
    broken = ReportWorkflow(
        request_for(registry, context, "malformed-report"), recording("malformed-report")
    ).run()
    phases = [s["phase"] for s in broken["steps"]]
    assert "fallback" in phases and broken["error_code"] == "EVIDENCE_VALIDATION_FAILED"
    assert broken["usage"]["requests"] <= 8


def test_review_lint_patches_direction_mismatch():
    registry, core, context, drill = registry_for("concentration")
    seed(registry, core, "zh")
    compare = core["compare_periods"]["evidence_id"]
    good = {
        "template": "净销售额较比较期变化 {{change}}。",
        "bindings": [
            {
                "name": "change",
                "evidence_id": compare,
                "path": "comparison.net_sales.change_rate",
                "format": "percent",
                "derive": None,
            }
        ],
    }
    wrong = {**good, "template": "净销售额较比较期下降 {{change}}。"}

    def transport(url, key, payload, timeout, protocol="openai_chat"):
        messages, flags = to_neutral(protocol, payload)
        last = str(messages[-1].get("content") or "")
        if "A review of your validated reply" in last:
            reply = {"patches": [{"at": "summary[0]", "sentence": good, "text": None, "ids": None}]}
        elif (phase_message(messages[-1]) or {}).get("phase") in {"refine", None} and len(
            messages
        ) == 2:
            reply = {"hypotheses": []}
        elif (phase_message(messages[-1]) or {}).get("phase") == "refine":
            reply = {"hypotheses": []}
        else:
            reply = analysis_with(wrong, registry.evidence)
        return from_neutral(protocol, json.dumps(reply, ensure_ascii=False), [])

    output = ReportWorkflow(request_for(registry, context, "custom"), transport).run()
    assert output["error_code"] is None, output["steps"]
    review = next(s for s in output["steps"] if s["phase"] == "review")
    assert review["lint"] == ["DIRECTION_MISMATCH"]
    assert next(s for s in output["steps"] if s["phase"] == "review_repair")["applied"]
    assert "下降" not in output["analysis"]["summary"][0]["text"]


def test_lint_flags_verification_metric_and_unrelated_note():
    registry, core, context, _ = registry_for("promotion_note")
    notes = core["get_merchant_notes"]
    ranked = core["rank_products"]
    other = next(
        i
        for i, p in enumerate(ranked["payload"]["items"])
        if p["sku"] not in notes["payload"]["items"][0]["text"]
    )
    raw = analysis_with(metric_facts(registry.evidence)[0], registry.evidence)
    raw["findings"][0]["topic"] = "refund"
    raw["findings"][0]["supporting"] = [
        {
            "template": "排名商品为 {{sku}}。",
            "bindings": [
                {
                    "name": "sku",
                    "evidence_id": ranked["evidence_id"],
                    "path": f"items.{other}.sku",
                    "format": "entity",
                }
            ],
        }
    ]
    raw["findings"][0]["hypotheses"] = [
        {
            "template": "可能与备注 {{note}} 有关。",
            "bindings": [
                {
                    "name": "note",
                    "evidence_id": notes["evidence_id"],
                    "path": "items.0.text",
                    "format": "note",
                }
            ],
        }
    ]
    codes = {i["code"]: i["at"] for i in lint(raw, registry.evidence)}
    assert codes["NO_VERIFICATION"] == "recommendations[0].verification_metric"
    assert codes["WEAK_NOTE_LINK"] == "findings[0].hypotheses[0]"


def test_question_budget_and_reused_hypotheses():
    registry, core, context, drill = registry_for("refund_spike")
    seed(registry, core, "zh")
    request = request_for(registry, context, "agent", kind="question")
    workflow = ReportWorkflow(request, transport_for("agent"), drill=drill)
    assert workflow.budgets == QUESTION_BUDGETS
    messages = workflow.initial_messages("native_tools", metric_facts(registry.evidence))
    data = json.loads(messages[1]["content"])
    assert {h["id"] for h in data["hypotheses"]} >= {"h_srv_refund_concentrated"}
    output = workflow.run()
    assert output["error_code"] is None
    assert output["usage"]["tools"] <= QUESTION_BUDGETS["tools"]
    assert output["usage"]["requests"] <= QUESTION_BUDGETS["requests"]


def test_anthropic_prompt_cache_breakpoints_and_cached_usage():
    messages = [
        {"role": "system", "content": "rules"},
        {"role": "user", "content": "evidence"},
        {"role": "assistant", "content": "plan", "tool_calls": []},
        {"role": "user", "content": "results"},
    ]
    tools = [{"name": "t", "description": "d", "parameters": {"type": "object"}}]
    payload = build("anthropic_messages", "m", messages, tools=tools, cache=True)
    assert payload["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert payload["messages"][0]["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert payload["messages"][2]["content"] == "results"
    assert isinstance(build("anthropic_messages", "m", messages)["system"], str)
    answer = parse(
        "anthropic_messages",
        {
            "type": "message",
            "role": "assistant",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "{}"}],
            "usage": {"input_tokens": 10, "cache_read_input_tokens": 90, "output_tokens": 5},
        },
    )
    assert answer["usage"]["input_tokens"] == 100 and answer["usage"]["cached_tokens"] == 90
    chat = parse(
        "openai_chat",
        completion_with_usage(
            {"prompt_tokens": 50, "prompt_tokens_details": {"cached_tokens": 40}}
        ),
    )
    assert chat["usage"]["cached_tokens"] == 40


def completion_with_usage(usage):
    return {
        "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "{}"}}],
        "usage": usage,
    }


def test_patch_targets_and_application():
    issues = [
        {"at": "summary[0].template", "code": "X"},
        {"at": "findings[1].supporting[0].bindings[1]", "code": "Y"},
        {"at": "recommendations[0].verification_metric", "code": "Z"},
    ]
    allowed = patches.targets(issues)
    assert allowed == {
        "summary[0]": "sentence",
        "findings[1].supporting[0]": "sentence",
        "recommendations[0].verification_metric": "text",
    }
    assert patches.targets([{"at": "$", "code": "INVALID_JSON"}]) is None
    raw = {
        "summary": [{"template": "a", "bindings": []}],
        "findings": [{}, {"supporting": [{"template": "b", "bindings": []}]}],
        "recommendations": [{"verification_metric": "net_sales"}],
    }
    sentence = {"template": "c", "bindings": []}
    patched = patches.apply(
        raw,
        {
            "patches": [
                {
                    "at": "findings[1].supporting[0]",
                    "sentence": sentence,
                    "text": None,
                    "ids": None,
                },
                {
                    "at": "recommendations[0].verification_metric",
                    "sentence": None,
                    "text": "refund_amount_rate",
                    "ids": None,
                },
            ]
        },
        allowed,
    )
    assert patched["findings"][1]["supporting"][0] == sentence
    assert patched["recommendations"][0]["verification_metric"] == "refund_amount_rate"
    assert raw["findings"][1]["supporting"][0]["template"] == "b"  # copy, not in place
    for bad in (
        {"at": "summary[3]", "sentence": sentence, "text": None, "ids": None},
        {"at": "findings[0].title", "sentence": None, "text": "x", "ids": None},
        {"at": "summary[0]", "sentence": None, "text": None, "ids": None},
    ):
        with pytest.raises(ValueError):
            patches.apply(raw, {"patches": [bad]}, allowed | {"summary[3]": "sentence"})


def test_report_service_persists_hypotheses_history_and_rechecks_revisions(
    api_client, db, isolated_storage, provider
):
    dataset_id = prepare_dataset(api_client)
    config = model_config(api_client, db, provider, "agent")
    item = create_report(api_client, dataset_id, model_id=config["id"]).json()["data"]
    report = finish_report(api_client, item)
    content = report["content"]
    assert content["schema_version"] == "3.0" and content["model_error_code"] is None
    assert content["generation_mode"] == "native_tools"
    assert content["hypotheses"] and {h["wave"] for h in content["hypotheses"]} >= {1}
    assert all(h["spec"] for h in content["hypotheses"])
    tools = {e["tool"] for e in content["evidence_index"]}
    assert {"test_hypothesis", "refund_breakdown"} <= tools
    runs = api_client.get(f"/api/v1/reports/{item['id']}/runs").json()["data"]
    assert runs[0]["budgets"]["tests"] == 10
    phases = [s["phase"] for s in runs[0]["steps"]]
    assert "test" in phases and "hypotheses" in phases and "review" in phases
    second = create_report(
        api_client, dataset_id, model_id=config["id"], parent_id=item["id"]
    ).json()["data"]
    revised = finish_report(api_client, second)["content"]
    rechecked = {h["id"]: h for h in revised["hypothesis_recheck"]}
    supported = [h["id"] for h in content["hypotheses"] if h["state"] == "supported"]
    assert supported and set(supported[:1]) <= set(rechecked)
    assert rechecked[supported[0]]["previous_state"] == "supported"


def test_review_model_runs_only_when_its_probe_passed():
    registry, core, context, drill = registry_for("refund_spike")
    seed(registry, core, "zh")
    models = []

    def transport(url, key, payload, timeout, protocol="openai_chat"):
        models.append(payload["model"])
        status, body = respond(protocol, payload)
        assert status == 200
        return body

    def run(**capabilities):
        models.clear()
        request = request_for(registry, context)
        request["config"]["review_model_name"] = "full"
        request["config"]["capabilities"].update(capabilities)
        output = ReportWorkflow(request, transport, drill=drill).run()
        assert output["error_code"] is None
        return output, next(s for s in output["steps"] if s["phase"] == "review")

    # Configs tested before the review probe carry no flag; failed probes record False.
    for capabilities in ({}, {"review_usable": False}):
        output, review = run(**capabilities)
        assert "full" not in models and review["model"] is None
    output, review = run(review_usable=True)
    assert models[-1] == "full" and review["model"] == []
    assert [s.get("model") for s in output["steps"] if s["phase"] == "model"][-1] == "full"


def test_real_provider_findings_schema_size_truncation_and_format_fallback():
    # Anthropic rejected the inlined report schema as "compiled grammar too large".
    from app.reports.schema import _inline_schema, output_schema

    for kind in ("report", "question"):
        shared = output_schema(kind)
        assert set(shared["$defs"]) == {"sentence", "binding"}
        assert len(json.dumps(shared)) < len(json.dumps(_inline_schema(kind))) / 2
        assert '"$ref": "#/$defs/sentence"' in json.dumps(shared)
    # A reply cut off by the output limit is named as such, not as a malformed response.
    for protocol, body in (
        (
            "anthropic_messages",
            {"type": "message", "role": "assistant", "stop_reason": "max_tokens", "content": []},
        ),
        (
            "openai_chat",
            {
                "choices": [
                    {"finish_reason": "length", "message": {"role": "assistant", "content": "{"}}
                ]
            },
        ),
    ):
        with pytest.raises(ProviderError, match="OUTPUT_TRUNCATED"):
            parse(protocol, body)
    # A provider refusing the output format (without tools) is retried once without it.
    registry, core, context, _ = registry_for("refund_spike")
    seed(registry, core, "zh")
    request = request_for(registry, context, "full")
    request["config"]["capabilities"]["json_schema"] = True
    sent = []

    def transport(url, key, payload, timeout, protocol="openai_chat"):
        sent.append(payload)
        if payload.get("response_format", {}).get("type") == "json_schema" and len(sent) == 1:
            raise ProviderError("UNSUPPORTED_REQUEST")
        return respond(protocol, {**payload, "model": "full"})[1]

    output = ReportWorkflow(request, transport).run()
    assert output["error_code"] is None
    assert "response_format" not in sent[1] and "tools" not in sent[0]


def test_rejected_statement_names_the_grammar_rule():
    registry, _, _, _ = registry_for("refund_spike")
    bad = {
        "id": "h_typed",
        "statement": {"template": "SP-AB 的退款占一半", "bindings": []},
        "test": {"tool": "refund_breakdown", "arguments": {"by": "sku"}},
        "expect": {
            "op": "share_ge",
            "a": {"source": "test", "path": "items.0.metrics.refund_amount"},
            "b": {"source": "test", "path": "total.metrics.refund_amount"},
            "threshold": "0.5",
        },
    }
    with pytest.raises(ToolError, match="INVALID_STATEMENT:UNBOUND_NUMBER_OR_CLAIM"):
        registry.execute("test_hypothesis", bad)


def test_a_confirmed_operand_of_an_estimated_verdict_is_not_marked_estimated():
    # Real TheLook report: gross profit (estimated) lags net sales (confirmed); binding the net
    # sales operand of that verdict rendered "+17.47%（估算）" from the verdict's overall quality.
    verdict = {
        "state": "supported",
        "quality": "estimated",
        "operands": [
            {"value": {"value": "0.1569", "unit": "ratio", "quality": "estimated"}},
            {"value": {"value": "0.1747", "unit": "ratio", "quality": "confirmed"}},
        ],
    }
    assert flagged(verdict, "operands.0.value", "quality", {"estimated"})
    assert not flagged(verdict, "operands.1.value", "quality", {"estimated"})
    assert flagged(verdict, "state", "quality", {"estimated"})
    assert flagged(
        {"items": [{"sample": "low", "metrics": {}}]}, "items.0.metrics", "sample", {"low"}
    )
