"""Summarise where agent runs spend model time, from the step events in `agent_runs`.

Read-only. Run from the repository root with the backend interpreter (it uses the configured
`DATABASE_URL`, like the API):

    backend/.venv/Scripts/python.exe scripts/agent_latency.py
    backend/.venv/Scripts/python.exe scripts/agent_latency.py --report <uuid> --since 2026-11-01
    backend/.venv/Scripts/python.exe scripts/agent_latency.py --limit 20 --json

Model steps carry no stage of their own, so each `model` step is assigned a phase from the
events around it (the workflow emits a marker before each stage, and the call's own step after
the call returns):

- `review`: the step names a `model` (only the review call overrides the main model).
- `plan`: after a hypothesis-mode `plan` marker.
- `repair`: after any `repair` marker (plan repairs, patch and full rewrites) and after the
  `review` marker (the review patch call).
- `refine` / `write`: after the wave-1 `hypotheses` marker the next call is the refine plan
  when something other than `validated`, a stage-less `repair` or `completed` follows it;
  otherwise it is already the final write. Calls after a wave-2 `hypotheses` or `finalize`
  marker are `write`.
- `tools` (v2 tool loop, questions and plan fallbacks): calls after a tool-mode `plan` marker
  that are followed by `tool` steps; the call that is not is the `write`.
- Failed attempts (steps with `error`) take the phase of the retry that follows them.

Edge case: a refine call whose run then dies before any write is counted as `write`.
Test-phase time is the wall time (`t_ms`) from the step before each wave's first test to the
wave's `hypotheses` marker, so it includes the server-side test queries and evidence reads.
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

PHASES = ("plan", "refine", "tools", "write", "repair", "review")
FINAL = {"validated", "completed"}


def classify(steps):
    """Return the inferred phase for each `model` step, in order."""
    phases, state, resume = [], None, None
    for index, step in enumerate(steps):
        kind = step.get("phase")
        after = steps[index + 1] if index + 1 < len(steps) else {}
        if kind == "plan":
            state = "plan" if step.get("mode") == "hypotheses" else "tools"
        elif kind == "repair":
            # A plan repair covers one call; the flow then continues where it was.
            resume = {"plan": "plan", "refine": "write"}.get(step.get("stage"))
            state = "repair"
        elif kind == "hypotheses":
            state = "after_wave" if step.get("wave") == 1 else "write"
        elif kind == "finalize":
            state = "write"
        elif kind == "review" and "lint" in step:
            state = "repair"
        elif kind != "model":
            continue
        elif step.get("model"):
            phases.append("review")
        elif step.get("error") and after.get("phase") == "model":
            phases.append(None)  # Resolved below from the retry it precedes.
        elif state == "after_wave":
            ends = step.get("error") or after.get("phase") in FINAL
            ends = ends or (after.get("phase") == "repair" and "stage" not in after)
            phases.append("write" if ends else "refine")
            state = "write"
        elif state == "tools":
            phases.append("tools" if after.get("phase") == "tool" or step.get("error") else "write")
        else:
            phases.append(state or "write")
            if state == "repair" and resume:
                state, resume = resume, None
    following = "write"
    for i in range(len(phases) - 1, -1, -1):
        if phases[i] is None:
            phases[i] = following
        else:
            following = phases[i]
    return phases


def test_time(steps):
    total, start = 0, None
    for index, step in enumerate(steps):
        if step.get("phase") == "test" and start is None and index:
            start = steps[index - 1].get("t_ms")
        elif step.get("phase") == "hypotheses":
            end = step.get("t_ms")
            if start is not None and end is not None:
                total += max(0, end - start)
            start = None
    return total


def summarize(runs):
    """`runs` are dicts with `id`, `report_id`, `created_at` and `steps`."""
    per_phase = {p: {"requests": 0, "latency_ms": 0} for p in PHASES}
    totals = {
        "runs": 0,
        "requests": 0,
        "failed_requests": 0,
        "latency_ms": 0,
        "test_ms": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cached_tokens": 0,
    }
    repairs, rows = {}, []
    for run in runs:
        steps = [s for s in run["steps"] or [] if isinstance(s, dict)]
        models = [s for s in steps if s.get("phase") == "model"]
        row = {
            "id": str(run["id"]),
            "report_id": str(run["report_id"]),
            "created_at": run["created_at"].isoformat() if run.get("created_at") else None,
            "requests": len(models),
            "latency_ms": 0,
            "test_ms": test_time(steps),
            **{p: 0 for p in PHASES},
        }
        for step, phase in zip(models, classify(steps), strict=True):
            latency = int(step.get("latency_ms") or 0)
            per_phase[phase]["requests"] += 1
            per_phase[phase]["latency_ms"] += latency
            row[phase] += latency
            row["latency_ms"] += latency
            totals["failed_requests"] += bool(step.get("error"))
            for key in ("input_tokens", "output_tokens", "cached_tokens"):
                totals[key] += int(step.get(key) or 0)
        for step in steps:
            if step.get("phase") == "repair":
                mode = step.get("mode") or "full"
                if step.get("stage"):
                    mode = "plan_" + mode
                repairs[mode] = repairs.get(mode, 0) + 1
            elif step.get("phase") == "review_repair":
                mode = "review_applied" if step.get("applied") else "review_rejected"
                repairs[mode] = repairs.get(mode, 0) + 1
        totals["runs"] += 1
        totals["requests"] += row["requests"]
        totals["latency_ms"] += row["latency_ms"]
        totals["test_ms"] += row["test_ms"]
        rows.append(row)
    count = max(1, totals["runs"])
    return {
        "totals": totals,
        "requests_per_run": round(totals["requests"] / count, 2),
        "latency_ms_per_run": round(totals["latency_ms"] / count),
        "cached_share": round(totals["cached_tokens"] / totals["input_tokens"], 4)
        if totals["input_tokens"]
        else 0.0,
        "phases": per_phase,
        "repair_modes": dict(sorted(repairs.items())),
        "runs": rows,
    }


def markdown(summary):
    t = summary["totals"]
    lines = [
        "# Agent latency",
        "",
        f"- Runs: {t['runs']}",
        f"- Model requests: {t['requests']} ({summary['requests_per_run']} per run, "
        f"{t['failed_requests']} failed attempts)",
        f"- Model latency: {t['latency_ms'] / 1000:.1f} s total, "
        f"{summary['latency_ms_per_run'] / 1000:.1f} s per run",
        f"- Test phase: {t['test_ms'] / 1000:.1f} s total",
        f"- Tokens: {t['input_tokens']} in, {t['output_tokens']} out, "
        f"{t['cached_tokens']} cached ({summary['cached_share']:.1%} of input)",
        "",
        "| Phase | Requests | Latency (s) | Share |",
        "| --- | ---: | ---: | ---: |",
    ]
    for phase, value in summary["phases"].items():
        share = value["latency_ms"] / t["latency_ms"] if t["latency_ms"] else 0
        lines.append(
            f"| {phase} | {value['requests']} | {value['latency_ms'] / 1000:.1f} | {share:.0%} |"
        )
    lines += ["", "| Repair mode | Count |", "| --- | ---: |"]
    lines += [f"| {k} | {v} |" for k, v in summary["repair_modes"].items()] or ["| (none) | 0 |"]
    lines += [
        "",
        "| Run | Created | Requests | Model (s) | " + " | ".join(PHASES) + " | Tests (s) |",
        "| --- | --- | ---: | ---: | " + " | ".join("---:" for _ in PHASES) + " | ---: |",
    ]
    for row in summary["runs"]:
        lines.append(
            f"| {row['id'][:8]} | {(row['created_at'] or '')[:16]} | {row['requests']} | "
            f"{row['latency_ms'] / 1000:.1f} | "
            + " | ".join(f"{row[p] / 1000:.1f}" for p in PHASES)
            + f" | {row['test_ms'] / 1000:.1f} |"
        )
    return "\n".join(lines) + "\n"


def load(report=None, since=None, limit=None):
    import uuid

    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from app.db import session as db_module
    from app.db.models import AgentRun

    query = select(AgentRun).order_by(AgentRun.created_at.desc())
    if report:
        query = query.where(AgentRun.report_id == uuid.UUID(report))
    if since:
        query = query.where(AgentRun.created_at >= since)
    if limit:
        query = query.limit(limit)
    with Session(db_module.engine()) as db:
        return [
            {
                "id": r.id,
                "report_id": r.report_id,
                "created_at": r.created_at,
                "steps": r.steps,
            }
            for r in db.scalars(query)
        ]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Agent run latency breakdown (read-only).")
    parser.add_argument("--report", help="only runs of this report id")
    parser.add_argument(
        "--since",
        type=lambda v: datetime.strptime(v, "%Y-%m-%d").replace(tzinfo=UTC),
        help="only runs created on or after this date (YYYY-MM-DD, UTC)",
    )
    parser.add_argument("--limit", type=int, help="newest N runs")
    parser.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    args = parser.parse_args(argv)
    summary = summarize(load(args.report, args.since, args.limit))
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(markdown(summary), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
