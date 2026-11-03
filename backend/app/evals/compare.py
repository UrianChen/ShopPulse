"""Compare two evaluation runs case by case (for prompt, grammar or model changes).

Repeated runs are averaged per case first, so a run with ``--repeat 3`` compares with a single
run. The output is Markdown: aggregate deltas, then every case whose outcome changed.
"""

from collections import defaultdict

from app.evals.judge import DIMENSIONS

HIGHER = (
    "success",
    "first_pass",
    "pipeline_accuracy",
    "cause_recall",
    "entity_coverage",
    "rule_mention",
    "hypothesis_cited",
    "hypothesis_validity",
    "deepened",
    "sku_drill",
    "ruled_out_listed",
    "tool_effectiveness",
    "patch_success",
    "cache_ratio",
    "note_mention",
    "followup_mention",
    "kind_match",
    *[f"judge_{d}" for d in DIMENSIONS],
)
LOWER = (
    "distractor_misuse",
    "overclaim_rate",
    "forbidden_hits",
    "lint_issues",
    "direction_flags",
    "derive_errors",
    "repair_rate",
    "requests",
    "latency_p50_ms",
    "latency_p90_ms",
    "input_tokens",
    "output_tokens",
)
CASE_KEYS = (
    "success",
    "pipeline_accuracy",
    "cause_recall",
    "distractor_misuse",
    "repairs",
    "requests",
    "latency_ms",
)


def number(value):
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)


def delta(before, after, lower):
    if not isinstance(before, int | float) or not isinstance(after, int | float):
        return "", ""
    change = after - before
    if change == 0:
        return "0", ""
    better = change < 0 if lower else change > 0
    return f"{change:+.4g}", "better" if better else "worse"


def per_case(run):
    grouped = defaultdict(list)
    for result in run.get("cases") or []:
        grouped[result["id"]].append(result)
    merged = {}
    for case_id, items in grouped.items():
        entry = {}
        for key in CASE_KEYS:
            values = [r[key] for r in items if isinstance(r.get(key), int | float)]
            entry[key] = sum(values) / len(values) if values else None
        entry["errors"] = sorted({r["error_code"] for r in items if r.get("error_code")})
        entry["cited"] = sorted({h for r in items for h in r.get("cited_hypotheses") or []})
        entry["ruled_out"] = sorted({h for r in items for h in r.get("ruled_out") or []})
        entry["pipeline_failures"] = sorted(
            {f for r in items for f in r.get("pipeline_failures") or []}
        )
        entry["texts"] = {t for r in items for t in r.get("texts") or []}
        merged[case_id] = entry
    return merged


def stopped(run):
    found = run.get("stopped")
    if not found:
        return ""
    return f"STOPPED by {found['reason']} after {found['cases_done']} case run(s)"


def label(run):
    text = (
        f"{run.get('suite')} · {run.get('policy')} · prompt {run.get('prompt_version')} · "
        f"repeat {run.get('repeat', 1)} · {run.get('created_at', '')[:19]}"
    )
    return f"{text} · **{stopped(run)}**" if stopped(run) else text


def markdown(before, after):
    lines = [
        "# Evaluation comparison",
        "",
        f"- Before: {label(before)}",
        f"- After: {label(after)}",
        "",
    ]
    for name, run in (("Before", before), ("After", after)):
        if stopped(run):
            lines += [
                f"> **{name} run incomplete:** {stopped(run)} (spend cap). Its aggregate covers "
                "only the case runs it finished; cases it never reached are marked not run.",
                "",
            ]
    lines += [
        "## Aggregate",
        "",
        "| Metric | Before | After | Change | |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    a, b = before.get("aggregate") or {}, after.get("aggregate") or {}
    for key in HIGHER + LOWER:
        if key not in a and key not in b:
            continue
        change, verdict = delta(a.get(key), b.get(key), key in LOWER)
        lines.append(
            f"| {key} | {number(a.get(key))} | {number(b.get(key))} | {change} | {verdict} |"
        )
    spread = after.get("spread") or {}
    if spread:
        lines += [
            "",
            "Spread of the after run (stdev across repeats): "
            + ", ".join(f"{k} {v['stdev']:.3g}" for k, v in spread.items() if k in HIGHER + LOWER),
        ]
    old, new = per_case(before), per_case(after)
    changed = []
    for case_id in sorted(old.keys() | new.keys()):
        x, y = old.get(case_id), new.get(case_id)
        if x is None or y is None:
            cut = stopped(before if x is None else after)
            if cut:
                side = "before" if x is None else "after"
                changed.append(f"### {case_id}\n\nNot run in {side} ({cut}).\n")
            else:
                changed.append(
                    f"### {case_id}\n\n{'Added' if x is None else 'Removed'} in after.\n"
                )
            continue
        notes = []
        for key in CASE_KEYS:
            if x[key] != y[key] and key != "latency_ms":
                notes.append(f"{key} {number(x[key])} → {number(y[key])}")
        for key in ("errors", "cited", "ruled_out", "pipeline_failures"):
            if x[key] != y[key]:
                notes.append(f"{key} {x[key] or '—'} → {y[key] or '—'}")
        gone, came = sorted(x["texts"] - y["texts"]), sorted(y["texts"] - x["texts"])
        if gone or came:
            notes.append(f"text: {len(gone)} sentence(s) removed, {len(came)} added")
        if notes:
            # Latency is wall-clock noise: shown next to real changes, never a change by itself.
            if x["latency_ms"] != y["latency_ms"]:
                notes.append(f"latency_ms {number(x['latency_ms'])} → {number(y['latency_ms'])}")
            body = "\n".join("- " + n for n in notes)
            samples = "".join(f"\n  - −{t}" for t in gone[:3]) + "".join(
                f"\n  - +{t}" for t in came[:3]
            )
            changed.append(f"### {case_id}\n\n{body}{samples}\n")
    lines += ["", f"## Changed cases ({len(changed)} of {len(old.keys() | new.keys())})", ""]
    lines += changed or ["No case changed."]
    return "\n".join(lines) + "\n"
