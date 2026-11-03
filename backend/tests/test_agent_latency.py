"""scripts/agent_latency.py: phase inference over step events, and the read-only summary."""

import importlib.util
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from app.db.models import AgentRun
from app.providers.mock_server import respond
from app.reports.hypothesis import seed
from app.reports.workflow import ReportWorkflow
from tests.test_agent_v3 import registry_for, request_for
from tests.test_metrics import prepare_dataset
from tests.test_reports import create_report, finish_report

spec = importlib.util.spec_from_file_location(
    "agent_latency", Path(__file__).resolve().parents[2] / "scripts" / "agent_latency.py"
)
latency = importlib.util.module_from_spec(spec)
spec.loader.exec_module(latency)


def model(ms, **extra):
    return {"phase": "model", "latency_ms": ms, "input_tokens": 1000, "output_tokens": 100, **extra}


# Hypotheses with a refine wave, a retried write, a patch repair, a review model and its patch.
DEEP = [
    {"phase": "computing"},
    {"phase": "analyzing"},
    {"phase": "plan", "mode": "hypotheses", "t_ms": 0},
    {**model(100), "t_ms": 100},
    {"phase": "test", "t_ms": 150},
    {"phase": "test", "t_ms": 250},
    {"phase": "hypotheses", "wave": 1, "t_ms": 300},
    {**model(200, cached_tokens=800), "t_ms": 500},
    {"phase": "test", "t_ms": 550},
    {"phase": "hypotheses", "wave": 2, "t_ms": 600},
    {"phase": "model", "latency_ms": 50, "error": "RATE_LIMITED"},
    model(300),
    {"phase": "repair", "codes": ["NUMBER_MISMATCH"], "mode": "patch"},
    model(40),
    {"phase": "validated", "repairs": 1},
    {**model(70), "model": "reviewer"},
    {"phase": "review", "lint": ["DIRECTION_MISMATCH"], "model": []},
    model(30),
    {"phase": "review_repair", "applied": True},
    {"phase": "completed", "error": None},
]
# An invalid plan repaired once, still invalid, then the v2 tool loop.
FALLBACK = [
    {"phase": "plan", "mode": "hypotheses"},
    model(100),
    {"phase": "repair", "codes": ["INVALID_PLAN"], "mode": "full", "stage": "plan"},
    model(100),
    {"phase": "fallback", "reason": "INVALID_PLAN"},
    {"phase": "plan", "goals": 2},
    model(100, tool_calls=["rank_products"]),
    {"phase": "tool", "ok": True},
    model(100),
    {"phase": "validated", "repairs": 0},
    {"phase": "review", "lint": [], "model": None},
]
# A refine plan repaired into an empty plan: the write follows the repair call directly.
REFINE_REPAIR = [
    {"phase": "plan", "mode": "hypotheses"},
    model(10),
    {"phase": "hypotheses", "wave": 1},
    model(10),
    {"phase": "repair", "codes": ["INVALID_PLAN"], "mode": "full", "stage": "refine"},
    model(10),
    model(10),
    {"phase": "validated"},
]


def test_phase_inference():
    assert latency.classify(DEEP) == [
        "plan",
        "refine",
        "write",
        "write",
        "repair",
        "review",
        "repair",
    ]
    assert latency.classify(FALLBACK) == ["plan", "repair", "tools", "write"]
    assert latency.classify(REFINE_REPAIR) == ["plan", "refine", "repair", "write"]
    no_refine = [
        {"phase": "plan", "mode": "hypotheses"},
        model(10),
        {"phase": "hypotheses", "wave": 1},
        model(10),
        {"phase": "validated"},
    ]
    assert latency.classify(no_refine) == ["plan", "write"]
    assert latency.test_time(DEEP) == 300


def test_phase_inference_on_real_workflow_steps():
    registry, core, context, drill = registry_for("refund_spike")
    seed(registry, core, "zh")
    request = request_for(registry, context)
    request["config"]["review_model_name"] = "full"
    request["config"]["capabilities"]["review_usable"] = True

    def transport(url, key, payload, timeout, protocol="openai_chat"):
        return respond(protocol, payload)[1]

    output = ReportWorkflow(request, transport, drill=drill).run()
    assert output["error_code"] is None
    assert latency.classify(output["steps"]) == ["plan", "refine", "write", "review"]


def test_summary_over_inserted_runs(api_client, db, isolated_storage, capsys):
    dataset_id = prepare_dataset(api_client)
    first = create_report(api_client, dataset_id).json()["data"]
    second = create_report(api_client, dataset_id).json()["data"]
    for item in (first, second):
        finish_report(api_client, item)
    base = {
        row.report_id: row
        for row in db.query(AgentRun).filter(AgentRun.report_id.in_([first["id"], second["id"]]))
    }
    assert len(base) == 2
    for report, steps, created in (
        (first["id"], DEEP, datetime(2026, 10, 2, tzinfo=UTC)),
        (first["id"], FALLBACK, datetime(2026, 10, 3, tzinfo=UTC)),
        (second["id"], REFINE_REPAIR, datetime(2026, 1, 1, tzinfo=UTC)),
    ):
        parent = base[uuid.UUID(report)]
        db.add(
            AgentRun(
                report_id=parent.report_id,
                job_id=parent.job_id,
                attempt=100 + len(steps),
                status="completed",
                budgets={},
                steps=steps,
                created_at=created,
            )
        )
    db.commit()

    summary = latency.summarize(
        [r for r in latency.load(report=first["id"]) if r["steps"] in (DEEP, FALLBACK)]
    )
    totals = summary["totals"]
    assert totals["runs"] == 2 and totals["requests"] == 11 and totals["failed_requests"] == 1
    assert totals["latency_ms"] == 790 + 400 and totals["test_ms"] == 300
    assert summary["phases"]["plan"] == {"requests": 2, "latency_ms": 200}
    assert summary["phases"]["write"] == {"requests": 3, "latency_ms": 450}
    assert summary["phases"]["repair"] == {"requests": 3, "latency_ms": 170}
    assert summary["phases"]["review"] == {"requests": 1, "latency_ms": 70}
    assert summary["phases"]["tools"] == {"requests": 1, "latency_ms": 100}
    assert totals["cached_tokens"] == 800 and summary["cached_share"] == round(800 / 10000, 4)
    assert summary["repair_modes"] == {"patch": 1, "plan_full": 1, "review_applied": 1}
    assert summary["requests_per_run"] == 5.5

    assert latency.main(["--report", first["id"], "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["totals"]["runs"] == 3 and data["totals"]["requests"] == 11
    assert latency.main(["--since", "2026-06-01", "--limit", "10"]) == 0
    text = capsys.readouterr().out
    assert text.startswith("# Agent latency") and "- Runs: 4" in text
    assert "| refine | 1 | 0.2 |" in text and "| plan_full | 1 |" in text
    assert latency.main(["--limit", "1", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["totals"]["runs"] == 1
    # Read-only: nothing was written.
    db.expire_all()
    assert db.query(AgentRun).count() == 5
